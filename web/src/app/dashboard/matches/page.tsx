'use client';

import { useEffect, useState } from 'react';
import { supabase } from '@/lib/supabaseClient';

interface JobMatch {
  id: string;
  score: number;
  reasoning: string | null;
  status: string;
  created_at: string;
  jobs: {
    title: string;
    url: string | null;
    location: string | null;
    companies: { name: string; favicon_url: string | null } | null;
  } | null;
}

export default function JobMatches() {
  const [matches, setMatches] = useState<JobMatch[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const { data } = await supabase
        .from('user_job_matches')
        .select('id, score, reasoning, status, created_at, jobs(title, url, location, companies(name, favicon_url))')
        .order('score', { ascending: false });
      setMatches((data as unknown as JobMatch[]) || []);
      setLoading(false);
    })();
  }, []);

  if (loading) {
    return <p className="subtitle">Loading matches...</p>;
  }

  return (
    <div>
      <h1 className="title text-gradient">Job Matches</h1>
      <p className="subtitle">Jobs the agent found at companies you track, scored against your resume and goals.</p>

      <div className="grid">
        {matches.map(match => {
          const job = match.jobs;
          const company = job?.companies;
          return (
            <div key={match.id} className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', minWidth: 0 }}>
                <img
                  src={company?.favicon_url || '/file.svg'}
                  alt=""
                  className="company-favicon"
                  onError={(e) => { (e.target as HTMLImageElement).src = '/file.svg'; }}
                />
                <div style={{ minWidth: 0 }}>
                  <h3 style={{ marginBottom: '0.25rem' }}>
                    {job?.url ? (
                      <a href={job.url} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                        {job?.title}
                      </a>
                    ) : (
                      job?.title
                    )}
                  </h3>
                  <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                    {company?.name}{job?.location ? ` — ${job.location}` : ''}
                  </p>
                  {match.reasoning && (
                    <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: '0.5rem' }}>{match.reasoning}</p>
                  )}
                </div>
              </div>
              <span className="status-badge status-approved" style={{ flexShrink: 0 }}>{match.score}/100</span>
            </div>
          );
        })}
        {matches.length === 0 && (
          <p className="subtitle">
            No matches yet — make sure you&apos;ve saved a resume/goals and subscribed to some companies.
          </p>
        )}
      </div>
    </div>
  );
}
