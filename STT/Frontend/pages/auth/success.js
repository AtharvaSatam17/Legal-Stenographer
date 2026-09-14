// pages/auth/success.js
import { useEffect } from 'react';
import { useRouter } from 'next/router';

export default function Success() {
  const router = useRouter();

  useEffect(() => {
    router.replace('/');
  }, []);

  return <p>Signing in...</p>;
}
