'use client';

import { useEffect, useMemo, useState } from 'react';
import { supabase } from '@/lib/supabaseClient';
import { basePath } from '@/lib/basePath';

interface Job {
  id: string;
  title: string;
  url: string | null;
  location: string | null;
  first_seen_at: string;
  companies: { name: string; favicon_url: string | null } | null;
}

export default function AllJobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [companyFilter, setCompanyFilter] = useState('all');

  useEffect(() => {
    (async () => {
      const { data } = await supabase
        .from('jobs')
        .select('id, title, url, location, first_seen_at, companies(name, favicon_url)')
        .eq('is_active', true)
        .order('first_seen_at', { ascending: false });
      setJobs((data as unknown as Job[]) || []);
      setLoading(false);
    })();
  }, []);

  const companyNames = useMemo(() => {
    const names = new Set(jobs.map(j => j.companies?.name).filter((n): n is string => Boolean(n)));
    return Array.from(names).sort();
  }, [jobs]);

  const filteredJobs = useMemo(() => {
    const query = search.trim().toLowerCase();
    return jobs.filter(job => {
      if (companyFilter !== 'all' && job.companies?.name !== companyFilter) return false;
      if (!query) return true;
      return (
        job.title.toLowerCase().includes(query) ||
        (job.location || '').toLowerCase().includes(query) ||
        (job.companies?.name || '').toLowerCase().includes(query)
      );
    });
  }, [jobs, search, companyFilter]);

  if (loading) {
    return <p className="subtitle">Loading jobs...</p>;
  }

  return (
    <div>
      <h1 className="title text-gradient">All Jobs</h1>
      <p className="subtitle">Every currently open posting the agent has found across tracked companies.</p>

      <div className="card" style={{ marginBottom: '2rem', display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
        <div className="input-group" style={{ flex: 2, minWidth: '240px', marginBottom: 0 }}>
          <label>Search</label>
          <input
            className="input-field"
            placeholder="Title, company, or location..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <div className="input-group" style={{ flex: 1, minWidth: '200px', marginBottom: 0 }}>
          <label>Company</label>
          <select className="input-field" value={companyFilter} onChange={e => setCompanyFilter(e.target.value)}>
            <option value="all">All companies</option>
            {companyNames.map(name => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </div>
      </div>

      <p className="subtitle" style={{ fontSize: '0.9rem' }}>{filteredJobs.length} of {jobs.length} job(s)</p>

      <div className="grid">
        {filteredJobs.map(job => (
          <div key={job.id} className="card" style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <img
              src={job.companies?.favicon_url || `${basePath}/file.svg`}
              alt=""
              className="company-favicon"
              onError={(e) => { (e.target as HTMLImageElement).src = `${basePath}/file.svg`; }}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <h3 style={{ marginBottom: '0.25rem' }}>
                {job.url ? (
                  <a href={job.url} target="_blank" rel="noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                    {job.title}
                  </a>
                ) : (
                  job.title
                )}
              </h3>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                {job.companies?.name}{job.location ? ` — ${job.location}` : ''}
              </p>
            </div>
          </div>
        ))}
        {filteredJobs.length === 0 && <p className="subtitle">No jobs match.</p>}
      </div>
    </div>
  );
}
