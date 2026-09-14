import Head from 'next/head';
import { useState, useEffect } from 'react';
import LegalTranscriptionSystem from '../components/legal/LegalTranscriptionSystem';

export default function Home() {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // For now, use a mock user. Replace with actual Cognito auth when ready.
    const mockUser = {
      username: 'court_reporter',
      name: 'Court Reporter',
      email: 'reporter@court.gov'
    };

    setUser(mockUser);
    setIsLoading(false);
  }, []);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading...</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <Head>
        <title>Legal Stenographer - Court Transcription System</title>
        <meta
          name="description"
          content="Real-time court transcription with AI-powered speaker diarization"
        />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <div className="min-h-screen bg-gray-50">
        <LegalTranscriptionSystem user={user} />
      </div>
    </>
  );
}
