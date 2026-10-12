import os
import json
import boto3
import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from botocore.exceptions import ClientError, NoCredentialsError


class S3StorageService:

    def cleanup_local_files(self, audio_file_path: Optional[Path]):
        """
        Delete local audio and diarization files after successful S3 upload
        """
        try:
            # Delete audio file
            if audio_file_path and audio_file_path.exists():
                audio_file_path.unlink()
                print(f"🗑️ Deleted local audio file: {audio_file_path}")

            # Delete diarization transcript files for this session
            diarization_dir = Path("/home/ubuntu/talekar-stt/Talekar-STT/Backend/diarization_output/diarization_Transcription")

            if diarization_dir.exists() and audio_file_path:
                base_name = audio_file_path.stem

                for file in diarization_dir.glob(f"{base_name}*"):
                    try:
                        file.unlink()
                        print(f"Deleted transcript file: {file}")
                    except Exception as e:
                        print(f" Could not delete {file}: {e}")

        except Exception as e:
            print(f" Cleanup error: {e}")

    def __init__(self):
        # Get AWS credentials from environment
        self.aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        self.bucket_name = "talekar-stt"
        self.region = "ap-south-1"
        
        if not self.aws_access_key_id or not self.aws_secret_access_key:
            raise ValueError("AWS credentials not found in environment variables")
        
        # Initialize S3 client
        try:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                region_name=self.region
            )
            print(f"✅ S3 client initialized for bucket: {self.bucket_name} in region: {self.region}")
        except Exception as e:
            raise Exception(f"Failed to initialize S3 client: {e}")

    def _get_folder_structure(self, user_sub: str, session_id: str) -> str:
        """
        Generate folder structure: user_sub/DD-MM-YYYY/session_id/
        """
        current_date = datetime.now()
        date_folder = current_date.strftime("%d-%m-%Y")
        
        folder_path = f"{user_sub}/{date_folder}/{session_id}/"
        return folder_path

    def _get_feedback_csv_path(self) -> str:
        """
        Generate CSV path for feedback: talekar-stt/feedback_YYYY_MM.csv
        """
        current_date = datetime.now()
        year_month = current_date.strftime("%Y_%m")
        return f"talekar-stt/feedback_{year_month}.csv"

    def serialize_datetime_objects(self, obj):
        """Recursively convert datetime objects to ISO format strings for JSON serialization"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        elif isinstance(obj, dict):
            return {key: self.serialize_datetime_objects(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self.serialize_datetime_objects(item) for item in obj]
        else:
            return obj

    def _upload_file_to_s3(self, file_content: bytes, s3_key: str, content_type: str = "application/octet-stream") -> bool:
        """
        Upload file content to S3
        
        Args:
            file_content: File content as bytes
            s3_key: S3 object key (full path)
            content_type: MIME type of the file
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=file_content,
                ContentType=content_type
            )
            print(f"✅ Uploaded to S3: s3://{self.bucket_name}/{s3_key}")
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            print(f"❌ S3 upload failed for {s3_key}: {error_code} - {e}")
            return False
        except Exception as e:
            print(f"❌ Unexpected error uploading {s3_key}: {e}")
            return False

    def _upload_text_to_s3(self, text_content: str, s3_key: str, content_type: str = "text/plain") -> bool:
        """
        Upload text content to S3
        """
        try:
            text_bytes = text_content.encode('utf-8')
            return self._upload_file_to_s3(text_bytes, s3_key, content_type)
        except Exception as e:
            print(f"❌ Error encoding text for {s3_key}: {e}")
            return False

    def _download_csv_from_s3(self, s3_key: str) -> Optional[str]:
        """
        Download existing CSV content from S3
        
        Returns:
            str: CSV content if exists, None if doesn't exist
        """
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=s3_key)
            return response['Body'].read().decode('utf-8')
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchKey':
                # File doesn't exist yet, which is fine
                return None
            else:
                print(f"❌ Error downloading CSV {s3_key}: {error_code}")
                return None
        except Exception as e:
            print(f"❌ Unexpected error downloading CSV {s3_key}: {e}")
            return None

    def _generate_feedback_row_id(self, feedback_data: Dict[str, Any]) -> str:
        """
        Generate a unique row ID for feedback to prevent duplicates
        Based on session_id, user_id, feedback_type, panel, feedback_text, and date
        """
        session_id = feedback_data.get('session_id', 'unknown')
        user_id = feedback_data.get('user_id', 'unknown')
        feedback_type = feedback_data.get('feedback_type', 'unknown')
        panel = feedback_data.get('panel', 'unknown')
        feedback_text = feedback_data.get('feedback_text', '').strip()
        
        # Parse timestamp to get date
        timestamp = feedback_data.get('timestamp')
        if isinstance(timestamp, str):
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except:
                dt = datetime.now()
        elif isinstance(timestamp, datetime):
            dt = timestamp
        else:
            dt = datetime.now()
        
        date_key = dt.strftime("%d-%m-%Y")
        
        # Create unique ID including feedback text to allow multiple feedback per panel
        row_id = f"{session_id}|{user_id}|{feedback_type}|{panel}|{feedback_text}|{date_key}"
        return row_id

    def _extract_existing_row_ids(self, csv_content: str) -> set:
        """
        Extract existing row IDs from CSV content to check for duplicates
        """
        if not csv_content:
            return set()
        
        existing_ids = set()
        try:
            reader = csv.reader(csv_content.splitlines())
            rows = list(reader)
            
            # Skip header row
            for row in rows[1:] if len(rows) > 1 else []:
                if len(row) >= 7:  # Ensure we have all required columns
                    # Extract components from the row to rebuild the ID
                    session_part = row[2].replace('Session=', '') if row[2].startswith('Session=') else row[2]
                    user_part = row[3].replace('User=', '') if row[3].startswith('User=') else row[3]
                    type_part = row[4].replace('Type=', '') if row[4].startswith('Type=') else row[4]
                    panel_part = row[6].replace('Panel=', '') if row[6].startswith('Panel=') else row[6]
                    
                    # Extract feedback text - handle the Text="..." format
                    text_part = row[5]
                    if text_part.startswith('Text="') and text_part.endswith('"'):
                        # Remove Text=" prefix and " suffix
                        feedback_text = text_part[6:-1]  # Remove 'Text="' and '"'
                    else:
                        feedback_text = text_part
                    
                    date_str = row[1]  # DD-MM-YYYY format
                    
                    # Create row ID including feedback text
                    row_id = f"{session_part}|{user_part}|{type_part}|{panel_part}|{feedback_text}|{date_str}"
                    existing_ids.add(row_id)
                        
        except Exception as e:
            print(f"⚠️ Error extracting existing row IDs: {e}")
            
        return existing_ids


    async def store_feedback_to_csv(self, feedback_data: Dict[str, Any]) -> bool:
        """
        Store feedback data to CSV in S3 bucket with duplicate prevention (ignoring feedback_text)
        Overwrites existing entry for same session_id, user_id, feedback_type, panel, and date.
        """
        try:
            # Extract feedback info
            session_id = feedback_data.get('session_id', 'unknown')
            user_id = feedback_data.get('user_id', 'unknown')
            feedback_type = feedback_data.get('feedback_type', 'unknown')
            feedback_text = feedback_data.get('feedback_text', '')
            panel = feedback_data.get('panel', 'unknown')

            # Normalize timestamp
            timestamp = feedback_data.get('timestamp')
            if isinstance(timestamp, str):
                try:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except:
                    dt = datetime.now()
            elif isinstance(timestamp, datetime):
                dt = timestamp
            else:
                dt = datetime.now()

            month = dt.strftime("%B")
            date = dt.strftime("%d-%m-%Y")

            # ✅ Generate row_id without feedback_text (so duplicates are caught)
            row_id = f"{session_id}|{user_id}|{feedback_type}|{panel}|{date}"

            # Get CSV path
            csv_s3_key = self._get_feedback_csv_path()
            print(f"📝 Storing feedback to CSV: {csv_s3_key}")
            print(f"   Row ID: {row_id}")

            # Download existing CSV
            existing_csv = self._download_csv_from_s3(csv_s3_key)

            csv_buffer = io.StringIO()
            writer = csv.writer(csv_buffer)
            headers = ['Month', 'Date', 'Session', 'User', 'Type', 'Text', 'Panel']

            existing_rows = []
            if existing_csv:
                reader = csv.reader(existing_csv.splitlines())
                existing_rows = list(reader)

                # Always keep header
                if existing_rows and existing_rows[0] == headers:
                    existing_rows = existing_rows[1:]
            else:
                # New file: write header first
                writer.writerow(headers)

            # Filter out existing rows with same row_id (overwrite mode)
            filtered_rows = []
            for row in existing_rows:
                if len(row) >= 7:
                    session_part = row[2].replace("Session=", "")
                    user_part = row[3].replace("User=", "")
                    type_part = row[4].replace("Type=", "")
                    panel_part = row[6].replace("Panel=", "")
                    date_part = row[1]
                    existing_id = f"{session_part}|{user_part}|{type_part}|{panel_part}|{date_part}"
                    if existing_id == row_id:
                        print(f"🔄 Overwriting existing feedback row: {existing_id}")
                        continue
                filtered_rows.append(row)

            # Write back remaining rows
            writer.writerows(filtered_rows)

            # Add new feedback row
            new_row = [
                month,
                date,
                f"Session={session_id}",
                f"User={user_id}",
                f"Type={feedback_type}",
                f"Text=\"{feedback_text}\"",
                f"Panel={panel}"
            ]
            writer.writerow(new_row)

            # Upload to S3
            csv_content = csv_buffer.getvalue()
            csv_buffer.close()

            success = self._upload_text_to_s3(
                csv_content,
                csv_s3_key,
                "text/csv; charset=utf-8"
            )

            if success:
                print(f"✅ Feedback stored/updated successfully in CSV: {csv_s3_key}")
                return True
            else:
                print(f"❌ Failed to upload feedback CSV: {csv_s3_key}")
                return False

        except Exception as e:
            print(f"❌ Error storing feedback to CSV: {e}")
            import traceback
            traceback.print_exc()
            return False


    async def upload_session_data(
        self,
        user_sub: str,
        session_id: str,
        audio_file_path: Optional[Path] = None,
        transcript: str = "",
        diarization_results: Optional[Dict[str, Any]] = None,
        legal_transcript: str = "",
        legal_transcript_json: Optional[Dict[str, Any]] = None,
        session_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Upload all session data to S3 (Legal version)

        Args:
            user_sub: User identifier from JWT
            session_id: Session ID
            audio_file_path: Path to audio recording file
            transcript: Full transcript text
            diarization_results: Speaker diarization results
            legal_transcript: Formatted legal transcript
            legal_transcript_json: Structured legal transcript JSON
            session_metadata: Additional session metadata

        Returns:
            Dict with upload results and S3 URLs
        """
        if not session_id:
            raise ValueError("session_id is required")
        
        # Get folder structure (now just session_id/)
        folder_path = self._get_folder_structure(user_sub, session_id)
        
        print(f"📁 Uploading session data to: s3://{self.bucket_name}/{folder_path}")
        
        upload_results = {
            "success": True,
            "folder_path": folder_path,
            "uploaded_files": {},
            "failed_files": {},
            "s3_urls": {}
        }
        
        try:
            # 1. Upload audio recording
            if audio_file_path and audio_file_path.exists():
                audio_s3_key = f"{folder_path}audio_recording.wav"
                
                try:
                    with open(audio_file_path, 'rb') as audio_file:
                        audio_content = audio_file.read()
                    
                    success = self._upload_file_to_s3(
                        audio_content, 
                        audio_s3_key, 
                        "audio/wav"
                    )
                    
                    if success:
                        upload_results["uploaded_files"]["audio"] = audio_s3_key
                        upload_results["s3_urls"]["audio"] = f"s3://{self.bucket_name}/{audio_s3_key}"
                    else:
                        upload_results["failed_files"]["audio"] = "Upload failed"
                        upload_results["success"] = False
                        
                except Exception as e:
                    print(f"❌ Error reading audio file {audio_file_path}: {e}")
                    upload_results["failed_files"]["audio"] = str(e)
                    upload_results["success"] = False
            else:
                print("⚠️ No audio file provided or file doesn't exist")
            
            # 2. Upload transcription
            if transcript and transcript.strip():
                transcript_s3_key = f"{folder_path}transcription.txt"
                
                success = self._upload_text_to_s3(
                    transcript.strip(),
                    transcript_s3_key,
                    "text/plain; charset=utf-8"
                )
                
                if success:
                    upload_results["uploaded_files"]["transcription"] = transcript_s3_key
                    upload_results["s3_urls"]["transcription"] = f"s3://{self.bucket_name}/{transcript_s3_key}"
                else:
                    upload_results["failed_files"]["transcription"] = "Upload failed"
                    upload_results["success"] = False
            else:
                print("⚠️ No transcript provided")
            
            # 3. Upload speaker diarization
            if diarization_results:
                diarization_s3_key = f"{folder_path}speaker_diarization.json"
                
                try:
                    # Serialize datetime objects first
                    serialized_diarization = self.serialize_datetime_objects(diarization_results)
                    diarization_json = json.dumps(serialized_diarization, indent=2, ensure_ascii=False)
                    
                    success = self._upload_text_to_s3(
                        diarization_json,
                        diarization_s3_key,
                        "application/json; charset=utf-8"
                    )
                    
                    if success:
                        upload_results["uploaded_files"]["diarization"] = diarization_s3_key
                        upload_results["s3_urls"]["diarization"] = f"s3://{self.bucket_name}/{diarization_s3_key}"
                    else:
                        upload_results["failed_files"]["diarization"] = "Upload failed"
                        upload_results["success"] = False
                        
                except Exception as e:
                    print(f"❌ Error serializing diarization data: {e}")
                    upload_results["failed_files"]["diarization"] = str(e)
                    upload_results["success"] = False
            else:
                print("⚠️ No diarization results provided")
            
            # 4. Upload formatted legal transcript
            if legal_transcript and legal_transcript.strip():
                legal_transcript_s3_key = f"{folder_path}legal_transcript.txt"

                success = self._upload_text_to_s3(
                    legal_transcript.strip(),
                    legal_transcript_s3_key,
                    "text/plain; charset=utf-8"
                )

                if success:
                    upload_results["uploaded_files"]["legal_transcript"] = legal_transcript_s3_key
                    upload_results["s3_urls"]["legal_transcript"] = f"s3://{self.bucket_name}/{legal_transcript_s3_key}"
                else:
                    upload_results["failed_files"]["legal_transcript"] = "Upload failed"
                    upload_results["success"] = False
            else:
                print("⚠️ No legal transcript provided")

            # 4b. Upload structured legal transcript JSON
            if legal_transcript_json:
                legal_json_s3_key = f"{folder_path}legal_transcript.json"

                try:
                    # Serialize datetime objects first
                    serialized_legal_json = self.serialize_datetime_objects(legal_transcript_json)
                    legal_json_str = json.dumps(serialized_legal_json, indent=2, ensure_ascii=False)

                    success = self._upload_text_to_s3(
                        legal_json_str,
                        legal_json_s3_key,
                        "application/json; charset=utf-8"
                    )

                    if success:
                        upload_results["uploaded_files"]["legal_transcript_json"] = legal_json_s3_key
                        upload_results["s3_urls"]["legal_transcript_json"] = f"s3://{self.bucket_name}/{legal_json_s3_key}"
                    else:
                        upload_results["failed_files"]["legal_transcript_json"] = "Upload failed"

                except Exception as e:
                    print(f"❌ Error serializing legal transcript JSON: {e}")
                    upload_results["failed_files"]["legal_transcript_json"] = str(e)
            else:
                print("⚠️ No legal transcript JSON provided")
            
            # 5. Upload session metadata (optional)
            if session_metadata:
                metadata_s3_key = f"{folder_path}session_metadata.json"
                
                try:
                    # Add upload timestamp to metadata
                    enhanced_metadata = {
                        **session_metadata,
                        "upload_timestamp": datetime.now().isoformat(),
                        "s3_folder": folder_path,
                        "user_sub": user_sub,
                        "session_id": session_id
                    }
                    
                    # Serialize datetime objects before JSON conversion
                    serialized_metadata = self.serialize_datetime_objects(enhanced_metadata)
                    metadata_json = json.dumps(serialized_metadata, indent=2, ensure_ascii=False)
                    
                    success = self._upload_text_to_s3(
                        metadata_json,
                        metadata_s3_key,
                        "application/json; charset=utf-8"
                    )
                    
                    if success:
                        upload_results["uploaded_files"]["metadata"] = metadata_s3_key
                        upload_results["s3_urls"]["metadata"] = f"s3://{self.bucket_name}/{metadata_s3_key}"
                    else:
                        upload_results["failed_files"]["metadata"] = "Upload failed"
                        
                except Exception as e:
                    print(f"❌ Error serializing session metadata: {e}")
                    upload_results["failed_files"]["metadata"] = str(e)

        except Exception as e:
            print(f"❌ Unexpected error during session upload: {e}")
            upload_results["success"] = False
            upload_results["error"] = str(e)
        
        # Summary

        uploaded_count = len(upload_results["uploaded_files"])
        failed_count = len(upload_results["failed_files"])

        if uploaded_count > 0:
            print(f"✅ Session upload completed: {uploaded_count} files uploaded, {failed_count} failed")

            # Cleanup local files only if upload succeeded
            if upload_results["success"]:
                self.cleanup_local_files(audio_file_path)

        else:
            print(f"❌ Session upload failed: No files uploaded")        
        return upload_results

    # Store evaluation data to S3

    async def store_evaluation_to_s3(self, evaluation_data: Dict[str, Any]) -> bool:
        """
        Store evaluation data to S3 in CSV format with monthly files and duplicate prevention
        Path: talekar-stt/evaluations_YYYY_MM.csv
        """
        try:
            # Extract evaluation info
            session_id = evaluation_data.get('session_id', 'unknown')
            user_id = evaluation_data.get('user_id', 'unknown')
            context = evaluation_data.get('context', 'Generic')
            ai_model = "claude-haiku3"
            
            # Get evaluation results
            evaluation_result = evaluation_data.get('evaluation_result', {})
            parsed_evaluation = evaluation_result.get('parsed_evaluation', {})

            # Extract scores from updated JSON structure
            transcript_eval = parsed_evaluation.get('transcript_evaluation', {})
            overall_assessment = parsed_evaluation.get('overall_assessment_score', 'Unknown')

            transcript_completeness = transcript_eval.get('completeness_score', 'Unknown')
            transcript_accuracy = transcript_eval.get('accuracy_score', 'Unknown')
            transcript_relevance = transcript_eval.get('relevance_score', 'Unknown')
            transcript_overall = transcript_eval.get('overall_score', 'Unknown')
            transcript_reasoning = "; ".join(transcript_eval.get('reasoning', [])) or ""

            key_findings = "; ".join(parsed_evaluation.get('key_findings', [])) or ""

            # Get stats
            eval_stats = evaluation_data.get('evaluation_stats', {})
            input_tokens = eval_stats.get('input_tokens', 0)
            output_tokens = eval_stats.get('output_tokens', 0)
            latency = eval_stats.get('latency_seconds', 0)

            # Normalize timestamp
            timestamp = evaluation_data.get('timestamp', datetime.now())
            if isinstance(timestamp, str):
                try:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except:
                    dt = datetime.now()
            elif isinstance(timestamp, datetime):
                dt = timestamp
            else:
                dt = datetime.now()

            month = dt.strftime("%B")
            date = dt.strftime("%d-%m-%Y")
            time_str = dt.strftime("%H:%M:%S")

            # Generate unique row identifier for duplicate detection
            # Using session_id + context + ai_model to identify unique evaluations
            row_identifier = f"{session_id}|{context}|{ai_model}"

            # Get evaluation CSV path
            current_date = datetime.now()
            year_month = current_date.strftime("%Y_%m")
            csv_s3_key = f"talekar-stt/evaluations_{year_month}.csv"
            
            print(f"📊 Storing evaluation to CSV: {csv_s3_key}")
            print(f"   Row identifier: {row_identifier}")

            # Download existing CSV
            existing_csv = self._download_csv_from_s3(csv_s3_key)

            csv_buffer = io.StringIO()
            writer = csv.writer(csv_buffer)

            # Define headers
            headers = [
                'Month', 'Date', 'Time', 'Session', 'User', 'Context', 'AI_Model',
                'Transcript_Completeness', 'Transcript_Accuracy', 'Transcript_Relevance',
                'Transcript_Overall', 'Transcript_Reasoning',
                'Overall_Assessment', 'Key_Findings',
                'Input_Tokens', 'Output_Tokens', 'Latency_Seconds'
            ]

            existing_rows = []
            existing_identifiers = set()
            
            # Process existing CSV and check for duplicates
            if existing_csv:
                reader = csv.reader(existing_csv.splitlines())
                existing_rows = list(reader)
                
                # Keep header if it matches
                if existing_rows and existing_rows[0] == headers:
                    existing_rows = existing_rows[1:]  # Remove header for processing
                    
                    # Extract identifiers from existing rows to check duplicates
                    for row in existing_rows:
                        if len(row) >= 7:  # Ensure we have required columns
                            existing_session = row[3].replace('Session=', '') if row[3].startswith('Session=') else row[3]
                            existing_context = row[5].replace('Context=', '') if row[5].startswith('Context=') else row[5]
                            existing_model = row[6].replace('Model=', '') if row[6].startswith('Model=') else row[6]
                            
                            existing_identifier = f"{existing_session}|{existing_context}|{existing_model}"
                            existing_identifiers.add(existing_identifier)

            # Check for duplicate
            if row_identifier in existing_identifiers:
                print(f"🔄 Duplicate evaluation found for identifier: {row_identifier}")
                print(f"   Overwriting existing evaluation entry")
                
                # Filter out the existing duplicate
                filtered_rows = []
                for row in existing_rows:
                    if len(row) >= 7:
                        existing_session = row[3].replace('Session=', '') if row[3].startswith('Session=') else row[3]
                        existing_context = row[5].replace('Context=', '') if row[5].startswith('Context=') else row[5]
                        existing_model = row[6].replace('Model=', '') if row[6].startswith('Model=') else row[6]
                        
                        existing_identifier = f"{existing_session}|{existing_context}|{existing_model}"
                        
                        if existing_identifier != row_identifier:
                            filtered_rows.append(row)
                        else:
                            print(f"   Removed duplicate row: {row[0]} {row[1]} {row[2]}")
                            
                existing_rows = filtered_rows
            else:
                print(f"✅ New evaluation entry (no duplicates found)")

            # Write header
            writer.writerow(headers)
            
            # Write existing rows (minus any duplicates)
            writer.writerows(existing_rows)
            

            # Add new evaluation row
            new_row = [
                month,
                date,
                time_str,
                f"Session={session_id}",
                f"User={user_id}",
                f"Context={context}",
                f"Model={ai_model}",
                transcript_completeness,
                transcript_accuracy,
                transcript_relevance,
                transcript_overall,
                transcript_reasoning,
                overall_assessment,
                key_findings,
                input_tokens,
                output_tokens,
                latency
            ]
            writer.writerow(new_row)

            # Upload to S3
            csv_content = csv_buffer.getvalue()
            csv_buffer.close()

            success = self._upload_text_to_s3(
                csv_content,
                csv_s3_key,
                "text/csv; charset=utf-8"
            )

            if success:
                print(f"✅ Evaluation stored successfully in CSV: {csv_s3_key}")
                return True
            else:
                print(f"❌ Failed to upload evaluation CSV: {csv_s3_key}")
                return False

        except Exception as e:
            print(f"❌ Error storing evaluation to CSV: {e}")
            import traceback
            traceback.print_exc()
            return False


    def get_session_urls(self, user_sub: str, session_id: str) -> Dict[str, str]:
        """
        Get S3 URLs for all session files (Legal version)
        """
        folder_path = self._get_folder_structure(user_sub, session_id)

        urls = {
            "audio": f"s3://{self.bucket_name}/{folder_path}audio_recording.wav",
            "transcription": f"s3://{self.bucket_name}/{folder_path}transcription.txt",
            "diarization": f"s3://{self.bucket_name}/{folder_path}speaker_diarization.json",
            "legal_transcript": f"s3://{self.bucket_name}/{folder_path}legal_transcript.txt",
            "legal_transcript_json": f"s3://{self.bucket_name}/{folder_path}legal_transcript.json",
            "metadata": f"s3://{self.bucket_name}/{folder_path}session_metadata.json"
        }

        return urls

    async def check_bucket_access(self) -> bool:
        """
        Check if we can access the S3 bucket
        """
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            print(f"✅ Successfully connected to bucket: {self.bucket_name}")
            return True
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                print(f"❌ Bucket {self.bucket_name} not found")
            else:
                print(f"❌ Cannot access bucket {self.bucket_name}: {error_code}")
            return False
        except NoCredentialsError:
            print(f"❌ AWS credentials not found or invalid")
            return False
        except Exception as e:
            print(f"❌ Unexpected error checking bucket access: {e}")
            return False

    def list_sessions_by_id(self, session_id_prefix: str = "") -> List[str]:
        """
        List all sessions (optionally filtered by session ID prefix)
        
        Args:
            session_id_prefix: Optional prefix to filter session IDs
            
        Returns:
            List of session IDs
        """
        try:
            prefix = f"{session_id_prefix}" if session_id_prefix else ""
            
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                Delimiter="/"
            )
            
            sessions = []
            if 'CommonPrefixes' in response:
                for prefix_info in response['CommonPrefixes']:
                    # Extract session ID from prefix
                    prefix_path = prefix_info['Prefix']
                    session_id = prefix_path.rstrip('/')
                    if session_id.startswith('realtime_'):
                        sessions.append(session_id)
            
            return sessions
            
        except Exception as e:
            print(f"Error listing sessions: {e}")
            return []