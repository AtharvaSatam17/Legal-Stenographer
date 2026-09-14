// pages/auth/callback.js
import { useEffect } from 'react';
import { useRouter } from 'next/router';
import axios from 'axios';
import Cookies from 'js-cookie';


const Callback = () => {
  const router = useRouter();
  const cognitoDomain = process.env.COGNITO_DOMAIN;
  const redirectUri = process.env.CALLBACK_URI;
  const clientId = process.env.COGNITO_CLIENT_ID;
  
  useEffect(() => {
    const handleAuth = async () => {
      console.log('Handling Callback for Authentication Attempt');
      const code = new URLSearchParams(window.location.search).get('code');
      if (!code) return;
      console.log('Authorization Code:', code);
      console.log('Cognito Domain:', cognitoDomain);
      console.log('Redirect URI:', redirectUri);
      const res = await axios.post(
        `${cognitoDomain}/oauth2/token`,        
        new URLSearchParams({
          grant_type: 'authorization_code',
          client_id:`${clientId}`,
          redirect_uri:  `${redirectUri}`,
          code
        }),
        {
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
        }
      );

      const { id_token, access_token } = res.data;
      Cookies.set('id_token', id_token, { path: '/' });
      Cookies.set('access_token', access_token, { path: '/' });

      router.push('/');
    };

    handleAuth();
  }, [router]);

  return <p>Logging in...</p>;
};

export default Callback;
