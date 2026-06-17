'use client';

import { useEffect, useState } from 'react';
import { supabase } from '@/lib/supabaseClient';

interface SearchResult {
  id: string;
  job_title: string;
  company_name: string | null;
  job_url: string;
  first_seen_at: string;
}

interface Search {
  id: string;
  search_url: string;
  last_scraped_at: string | null;
  results: SearchResult[];
}

export default function LinkedInTracking() {
  const [userId, setUserId] = useState<string | null>(null);
  const [searches, setSearches] = useState<Search[]>([]);
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) {
      setLoading(false);
      return;
    }
    setUserId(user.id);

    const { data: searchRows } = await supabase
      .from('linkedin_searches')
      .select('id, search_url, last_scraped_at')
      .eq('user_id', user.id)
      .order('created_at', { ascending: false });

    const withResults: Search[] = [];
    for (const row of searchRows || []) {
      const { data: results } = await supabase
        .from('linkedin_search_results')
        .select('id, job_title, company_name, job_url, first_seen_at')
        .eq('search_id', row.id)
        .order('first_seen_at', { ascending: false });
      withResults.push({ ...row, results: results || [] });
    }

    setSearches(withResults);
    setLoading(false);
  }

  async function addSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!userId) return;
    setSubmitting(true);

    const { error } = await supabase.from('linkedin_searches').insert({ user_id: userId, search_url: url });
    if (error) {
      alert(error.message);
    } else {
      setUrl('');
      await loadData();
    }
    setSubmitting(false);
  }

  async function removeSearch(id: string) {
    await supabase.from('linkedin_searches').delete().eq('id', id);
    setSearches(searches.filter(s => s.id !== id));
  }

  if (loading) {
    return <p className="subtitle">Loading...</p>;
  }

  return (
    <div>
      <h1 className="title text-gradient">LinkedIn Search Tracking</h1>
      <p className="subtitle">
        Add LinkedIn search URLs for the agent to monitor daily. This scrapes logged-out
        (no LinkedIn account connected), so results may be thin — up to 50 new jobs checked per search per run.
      </p>

      <div className="card" style={{ marginBottom: '2rem' }}>
        <h2 style={{ marginBottom: '1rem' }}>Add New Search</h2>
        <form onSubmit={addSearch}>
          <div className="input-group">
            <label>LinkedIn Job Search URL</label>
            <input
              type="url"
              className="input-field"
              placeholder="https://www.linkedin.com/jobs/search/?keywords=..."
              value={url}
              onChange={e => setUrl(e.target.value)}
              required
            />
          </div>
          <button type="submit" className="btn" disabled={submitting}>
            {submitting ? 'Adding...' : 'Add Monitor'}
          </button>
        </form>
      </div>

      <h2 style={{ marginBottom: '1rem' }}>Active Monitors</h2>
      <div className="grid">
        {searches.map(search => (
          <div key={search.id} className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: search.results.length > 0 ? '1rem' : 0 }}>
              <div style={{ minWidth: 0 }}>
                <h3 style={{ marginBottom: '0.25rem', wordBreak: 'break-all' }}>{search.search_url}</h3>
                <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                  {search.last_scraped_at
                    ? `Last checked: ${new Date(search.last_scraped_at).toLocaleString()} • ${search.results.length} job(s) found so far`
                    : 'Not scraped yet'}
                </p>
              </div>
              <button className="btn btn-secondary" onClick={() => removeSearch(search.id)} style={{ flexShrink: 0, marginLeft: '1rem' }}>
                Remove
              </button>
            </div>
            {search.results.length > 0 && (
              <ul style={{ listStyle: 'none', display: 'grid', gap: '0.5rem' }}>
                {search.results.map(result => (
                  <li key={result.id}>
                    <a href={result.job_url} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', textDecoration: 'none' }}>
                      {result.job_title}
                    </a>
                    {result.company_name && <span style={{ color: 'var(--text-muted)' }}> — {result.company_name}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
        {searches.length === 0 && <p className="subtitle">No searches added yet.</p>}
      </div>
    </div>
  );
}
