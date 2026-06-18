'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { supabase } from '@/lib/supabaseClient';
import { basePath } from '@/lib/basePath';

export default function Home() {
  const router = useRouter();
  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  // Supabase confirmation links (email confirm, magic link, etc.) redirect back here
  // with the session in the URL hash. supabase-js parses that hash automatically and
  // fires onAuthStateChange — without this, the user would land here logged in but
  // stuck looking at an empty login form.
  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) router.push('/dashboard');
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      if (session) router.push('/dashboard');
    });

    return () => subscription.unsubscribe();
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    if (mode === 'signin') {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) alert(error.message);
      else router.push('/dashboard');
    } else {
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        // Redirect back to wherever this is actually running (localhost in dev,
        // the GitHub Pages basePath in prod) instead of whatever fixed Site URL
        // is configured in the Supabase dashboard.
        options: { emailRedirectTo: `${window.location.origin}${window.location.pathname}` },
      });
      if (error) {
        alert(error.message);
      } else if (data.session) {
        router.push('/dashboard');
      } else {
        alert('Account created — check your email to confirm it, then sign in.');
        setMode('signin');
      }
    }

    setLoading(false);
  };

  return (
    <main className="container flex-center" style={{ minHeight: '100vh' }}>
      <div className="card" style={{ maxWidth: '400px', width: '100%' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
          <img src={`${basePath}/icon.svg`} alt="" width={40} height={40} />
          <h1 className="title text-gradient" style={{ fontSize: '2.5rem', marginBottom: 0 }}>
            {mode === 'signin' ? 'Agent Login' : 'Create Account'}
          </h1>
        </div>
        <p className="subtitle" style={{ textAlign: 'center' }}>
          {mode === 'signin' ? 'Enter your credentials to continue' : 'Sign up, then wait to be whitelisted'}
        </p>

        <form onSubmit={handleSubmit} className="grid">
          <div className="input-group">
            <label>Email</label>
            <input
              type="email"
              className="input-field"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="input-group">
            <label>Password</label>
            <input
              type="password"
              className="input-field"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
          </div>

          <button type="submit" className="btn" disabled={loading}>
            {loading ? 'Please wait...' : mode === 'signin' ? 'Sign In' : 'Sign Up'}
          </button>
        </form>

        <p className="subtitle" style={{ textAlign: 'center', fontSize: '0.9rem', marginTop: '1.5rem', marginBottom: 0 }}>
          {mode === 'signin' ? (
            <>Don&apos;t have an account?{' '}
              <button type="button" className="link-btn" onClick={() => setMode('signup')}>Sign up</button>
            </>
          ) : (
            <>Already have an account?{' '}
              <button type="button" className="link-btn" onClick={() => setMode('signin')}>Sign in</button>
            </>
          )}
        </p>
      </div>
    </main>
  );
}
