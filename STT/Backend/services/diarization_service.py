# services/diarization_service.py
import os
import json
import glob
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from utils.audio_utils import create_wav_buffer
import subprocess

class DiarizationService:

    def __init__(self, sarvam_service):

        self.sarvam_service = sarvam_service
        
        # Output directories
        self.recordings_dir = Path("/home/ubuntu/talekar-stt/Talekar-STT/Backend/diarization_output/Conversation_Recordings")
        self.transcripts_dir = Path("/home/ubuntu/talekar-stt/Talekar-STT/Backend/diarization_output/diarization_Transcription")
        
        # Create directories if they don't exist
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        
        # Processing stats
        self.timing_stats = {}

    def format_duration(self, seconds: float) -> str:
        """Format duration in a human-readable format"""
        if seconds < 60:
            return f"{seconds:.2f} seconds"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            remaining_seconds = seconds % 60
            return f"{minutes}m {remaining_seconds:.2f}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            remaining_seconds = seconds % 60
            return f"{hours}h {minutes}m {remaining_seconds:.2f}s"

    async def save_conversation_audio(
        self, 
        session_id: str, 
        audio_chunks: List[bytes], 
        sample_rate: int = 16000,
        channels: int = 1
    ) -> Optional[Path]:
        """
        Save accumulated audio chunks as a complete conversation recording
        
        Args:
            session_id: Unique session identifier
            audio_chunks: List of audio byte chunks
            sample_rate: Audio sample rate
            channels: Number of audio channels
            
        Returns:
            Path to saved audio file, or None if failed
        """
        if not audio_chunks:
            print(f"No audio chunks to save for session: {session_id}")
            return None

        try:
            # Combine all audio chunks
            combined_audio = b''.join(audio_chunks)
            
            # Create WAV buffer with proper headers
            wav_buffer = create_wav_buffer(combined_audio, sample_rate, channels)
            
            # Create filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{session_id}_{timestamp}.wav"
            file_path = self.recordings_dir / filename
            
            # Save to file
            with open(file_path, 'wb') as f:
                f.write(wav_buffer)
            
            print(f"Conversation audio saved: {file_path}")
            print(f"File size: {len(wav_buffer) / (1024*1024):.2f} MB")
            print(f"Duration: ~{len(combined_audio) / (sample_rate * channels * 2):.2f} seconds")
            
            return file_path
            
        except Exception as e:
            print(f"Failed to save conversation audio for {session_id}: {e}")
            return None

    async def process_diarization(
        self, 
        audio_file_path: Path, 
        num_speakers: int = 2,
        model: str = "saarika:v2.5"
    ) -> Dict[str, Any]:
        """
        Process speaker diarization on audio file
        
        Args:
            audio_file_path: Path to audio file
            num_speakers: Expected number of speakers
            model: Sarvam model to use
            
        Returns:
            Dictionary with diarization results and stats
        """
        if not audio_file_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

        # Initialize timing stats
        total_start_time = time.time()
        self.timing_stats = {
            'start_time': datetime.now(),
            'audio_file': str(audio_file_path)
        }
        
        print(f" Starting diarization for: {audio_file_path}")
        print(f" Expected speakers: {num_speakers}")
        print(f" Started at: {self.timing_stats['start_time'].strftime('%Y-%m-%d %H:%M:%S')}")

        try:
            # Convert to proper WAV format if needed
            converted_file = await self._convert_to_wav(str(audio_file_path))
            
            # Create diarization job
            print("📡 Creating diarization job...")
            job_creation_start = time.time()

            job = await self.sarvam_service.create_diarization_job(
                language_code="en-IN",
                model=model,
                num_speakers=num_speakers
            )
            self.timing_stats['job_creation_time'] = time.time() - job_creation_start
            print(f"✅ Job created in {self.format_duration(self.timing_stats['job_creation_time'])}")

            # Upload file
            print("📤 Uploading audio file...")
            upload_start = time.time()
            await job.upload_files([converted_file])
            self.timing_stats['upload_time'] = time.time() - upload_start
            print(f"✅ File uploaded in {self.format_duration(self.timing_stats['upload_time'])}")

            # Start job
            print(" Starting diarization job...")
            job_start_time = time.time()
            await job.start()
            
            # Wait for completion
            print("⏳ Waiting for job to complete...")
            processing_start = time.time()
            final_status = await job.wait_until_complete()
            processing_time = time.time() - processing_start
            total_job_time = time.time() - job_start_time
            
            self.timing_stats['processing_time'] = processing_time
            self.timing_stats['total_job_time'] = total_job_time
            
            print(f"✅ Job completed with status: {final_status}")
            print(f"⏱️  Processing took: {self.format_duration(processing_time)}")

            # Check if failed
            if await job.is_failed():
                error = await job.get_error()
                raise Exception(f"Diarization job failed: {error}")

            # Download results to temporary directory
            print("📥 Downloading results...")
            download_start = time.time()
            temp_output_dir = tempfile.mkdtemp()
            await job.download_outputs(output_dir=temp_output_dir)
            self.timing_stats['download_time'] = time.time() - download_start
            print(f"✅ Results downloaded in {self.format_duration(self.timing_stats['download_time'])}")

            # Process and save results
            results = await self._process_diarization_results(temp_output_dir, audio_file_path)
            
            # Calculate total time
            total_time = time.time() - total_start_time
            self.timing_stats['total_time'] = total_time
            self.timing_stats['end_time'] = datetime.now()
            
            # Add timing stats to results
            results['timing_stats'] = self.timing_stats
            
            # Cleanup
            try:
                os.unlink(converted_file)
                shutil.rmtree(temp_output_dir)
            except Exception as e:
                print(f"Cleanup error: {e}")

            print(f"🏁 Diarization completed in {self.format_duration(total_time)}")
            return results

        except Exception as e:
            print(f"❌ Diarization processing failed: {e}")
            raise

    async def _convert_to_wav(self, file_path: str) -> str:
        """Convert input file to 16kHz mono WAV if needed"""
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg not found. Please install ffmpeg")

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        temp_file.close()

        print(f"🔄 Converting {file_path} to WAV format...")
        conversion_start = time.time()
        
        cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            temp_file.name
        ]


        result = subprocess.run(cmd, capture_output=True, text=True)
        conversion_time = time.time() - conversion_start
        self.timing_stats['conversion_time'] = conversion_time
        
        if result.returncode != 0:
            raise Exception(f"File conversion failed: {result.stderr}")

        print(f"✅ File converted successfully in {self.format_duration(conversion_time)}")
        return temp_file.name

    async def _process_diarization_results(self, temp_output_dir: str, original_audio_path: Path) -> Dict[str, Any]:
        """Process and save diarization results"""
        
        # Find JSON result files
        json_files = glob.glob(os.path.join(temp_output_dir, "*.json"))
        
        if not json_files:
            raise Exception("No diarization result files found")

        print(f"📋 Processing {len(json_files)} result file(s)")
        
        all_results = []
        
        for json_file in json_files:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Extract transcript and segments
            full_transcript = data.get('transcript', '')
            segments = None
            
            if 'diarized_transcript' in data and 'entries' in data['diarized_transcript']:
                segments = data['diarized_transcript']['entries']
            
            if segments and isinstance(segments, list) and segments:
                result = {
                    'full_transcript': full_transcript,
                    'diarized_segments': segments,
                    'raw_data': data
                }
                all_results.append(result)
        
        if not all_results:
            raise Exception("No valid diarization segments found")
        
        # Use the first result (assuming single audio file)
        main_result = all_results[0]
        segments = main_result['diarized_segments']
        full_transcript = main_result['full_transcript']
        
        # Generate statistics
        speakers = set()
        total_duration = 0
        
        for seg in segments:
            if isinstance(seg, dict):
                speaker = seg.get('speaker_id')
                if speaker:
                    speakers.add(str(speaker))
                
                end_time = seg.get('end_time_seconds', 0)
                total_duration = max(total_duration, float(end_time))
        
        stats = {
            'total_speakers': len(speakers),
            'speaker_ids': sorted(speakers),
            'total_segments': len(segments),
            'total_duration_seconds': total_duration
        }
        
        # Add processing speed metrics
        if 'processing_time' in self.timing_stats and total_duration > 0:
            speed_ratio = total_duration / self.timing_stats['processing_time']
            stats['processing_speed_ratio'] = speed_ratio
            stats['realtime_processing'] = speed_ratio >= 1.0
        
        print(f"📊 Diarization Summary:")
        print(f"   • Total speakers detected: {stats['total_speakers']}")
        print(f"   • Speaker IDs: {', '.join(stats['speaker_ids'])}")
        print(f"   • Total duration: {total_duration:.2f} seconds")
        print(f"   • Total segments: {stats['total_segments']}")
        
        # Save formatted results
        output_files = await self._save_formatted_results(
            segments, full_transcript, original_audio_path, stats
        )
        
        return {
            'success': True,
            'full_transcript': full_transcript,
            'diarized_segments': segments,
            'statistics': stats,
            'output_files': output_files,
            'raw_data': main_result['raw_data']
        }

    async def _save_formatted_results(
        self,
        segments: List[Dict],
        full_transcript: str,
        original_audio_path: Path,
        stats: Dict
    ) -> Dict[str, str]:
        """Save diarization results in multiple formats (including legal format)"""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = original_audio_path.stem

        output_files = {}

        # Create multiple output formats
        formats = {
            'txt': self._create_text_format,
            'json': self._create_json_format,
            'srt': self._create_srt_format
        }

        for ext, formatter in formats.items():
            output_file = self.transcripts_dir / f"{base_name}_diarized_{timestamp}.{ext}"
            try:
                content = formatter(segments, full_transcript, stats)
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                output_files[ext] = str(output_file)
                print(f"📄 Created {ext.upper()} output: {output_file}")
            except Exception as e:
                print(f"❌ Error creating {ext.upper()} file: {e}")

        return output_files

    def _create_text_format(self, segments: List[Dict], full_transcript: str, stats: Dict) -> str:
        """Create human-readable text format"""
        content = []
        content.append("=" * 60)
        content.append("SPEAKER DIARIZATION RESULTS")
        content.append("=" * 60)
        content.append("")
        
        # Add processing information
        if self.timing_stats:
            content.append("PROCESSING SUMMARY:")
            content.append("-" * 30)
            if 'start_time' in self.timing_stats:
                content.append(f"Processed at: {self.timing_stats['start_time'].strftime('%Y-%m-%d %H:%M:%S')}")
            if 'total_time' in self.timing_stats:
                content.append(f"Total processing time: {self.format_duration(self.timing_stats['total_time'])}")
            if 'processing_time' in self.timing_stats:
                content.append(f"API processing time: {self.format_duration(self.timing_stats['processing_time'])}")
            content.append("")
        
        # Add statistics
        content.append(f"Total Duration: {stats['total_duration_seconds']:.2f} seconds")
        content.append(f"Speakers Detected: {stats['total_speakers']} ({', '.join(stats['speaker_ids'])})")
        content.append(f"Total Segments: {stats['total_segments']}")
        
        if 'processing_speed_ratio' in stats:
            content.append(f"Processing Speed: {stats['processing_speed_ratio']:.2f}x realtime")
        
        content.append("")
        content.append("-" * 60)
        content.append("FULL TRANSCRIPT:")
        content.append("-" * 60)
        content.append(full_transcript)
        content.append("")
        content.append("-" * 60)
        content.append("SPEAKER-SEPARATED TRANSCRIPT:")
        content.append("-" * 60)
        content.append("")
        
        for i, segment in enumerate(segments, 1):
            speaker = segment.get('speaker_id', 'Unknown')
            start_time = segment.get('start_time_seconds', 0)
            end_time = segment.get('end_time_seconds', 0)
            text = segment.get('transcript', '')
            
            content.append(f"[{i:02d}] {speaker} ({start_time:.2f}s - {end_time:.2f}s):")
            content.append(f"    {text}")
            content.append("")
        
        return "\n".join(content)

    def _create_json_format(self, segments: List[Dict], full_transcript: str, stats: Dict) -> str:
        """Create structured JSON format"""
        metadata = {
            **stats,
            "created_at": datetime.now().isoformat(),
        }
        
        # Add processing timing if available
        if self.timing_stats:
            metadata["processing_stats"] = {
                "total_processing_time": self.timing_stats.get('total_time'),
                "api_processing_time": self.timing_stats.get('processing_time'),
                "conversion_time": self.timing_stats.get('conversion_time'),
                "upload_time": self.timing_stats.get('upload_time'),
                "download_time": self.timing_stats.get('download_time')
            }
        
        output = {
            "metadata": metadata,
            "full_transcript": full_transcript,
            "diarized_segments": [
                {
                    "segment_id": i,
                    "speaker_id": seg.get('speaker_id', 'Unknown'),
                    "start_time_seconds": seg.get('start_time_seconds', 0),
                    "end_time_seconds": seg.get('end_time_seconds', 0),
                    "duration_seconds": seg.get('end_time_seconds', 0) - seg.get('start_time_seconds', 0),
                    "transcript": seg.get('transcript', '')
                }
                for i, seg in enumerate(segments, 1)
            ]
        }
        
        return json.dumps(output, indent=2, ensure_ascii=False)

    def _create_srt_format(self, segments: List[Dict], full_transcript: str, stats: Dict) -> str:
        """Create SRT subtitle format"""
        content = []
        
        for i, segment in enumerate(segments, 1):
            start_time = segment.get('start_time_seconds', 0)
            end_time = segment.get('end_time_seconds', 0)
            text = segment.get('transcript', '')
            speaker = segment.get('speaker_id', 'Unknown')
            
            # Convert seconds to SRT time format (HH:MM:SS,mmm)
            start_srt = self._seconds_to_srt_time(start_time)
            end_srt = self._seconds_to_srt_time(end_time)
            
            content.append(str(i))
            content.append(f"{start_srt} --> {end_srt}")
            content.append(f"[{speaker}] {text}")
            content.append("")
        
        return "\n".join(content)

    def _seconds_to_srt_time(self, seconds: float) -> str:
        """Convert seconds to SRT time format"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"