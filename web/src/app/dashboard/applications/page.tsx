'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApplicationStatusBadge } from '@/components/ApplicationStatusBadge';
import { ApplicationAnswerReview } from '@/components/ApplicationAnswerReview';
import {
  APPLICATION_GROUPS,
  APPLICATION_STATUS_META,
  ApplicationStatus,
  ApplicationStatusGroup,
  isApplicationStatus,
} from '@/lib/applicationStatus';
import { basePath } from '@/lib/basePath';
import { supabase } from '@/lib/supabaseClient';

interface ApplicationJob {
  id: string;
  title: string;
  url: string | null;
  location: string | null;
  companies: { name: string; favicon_url: string | null } | null;
}

interface ApplicationEvent {
  id: string;
  event_type: string;
  from_status: string | null;
  to_status: string | null;
  actor: string;
  message: string | null;
  created_at: string;
}

interface Application {
  id: string;
  user_id: string;
  job_id: string;
  status: ApplicationStatus;
  mode: string;
  adapter: string | null;
  target_url: string | null;
  form_fingerprint: string | null;
  unknown_fields: unknown;
  form_snapshot: unknown;
  answers_snapshot: unknown;
  last_error: string | null;
  confirmation_id: string | null;
  confirmation_url: string | null;
  evidence_path: string | null;
  queued_at: string;
  submitted_at: string | null;
  created_at: string;
  updated_at: string;
  jobs: ApplicationJob | null;
  application_events: ApplicationEvent[];
}

type ApplicationFilter = 'all' | ApplicationStatusGroup;

const APPLICATION_SELECT = `
  id,
  user_id,
  job_id,
  status,
  mode,
  adapter,
  target_url,
  form_fingerprint,
  unknown_fields,
  form_snapshot,
  answers_snapshot,
  last_error,
  confirmation_id,
  confirmation_url,
  evidence_path,
  queued_at,
  submitted_at,
  created_at,
  updated_at,
  jobs(id, title, url, location, companies(name, favicon_url)),
  application_events(id, event_type, from_status, to_status, actor, message, created_at)
`;

function formatTimestamp(value: string | null) {
  if (!value) return 'Not recorded';
  return new Date(value).toLocaleString();
}

function humanize(value: string) {
  return value.replaceAll('_', ' ');
}

function unknownFieldLabels(value: unknown): string[] {
  if (!value) return [];
  const fields = Array.isArray(value) ? value : [value];

  return fields.map((field) => {
    if (typeof field === 'string') return field;
    if (field && typeof field === 'object') {
      const candidate = field as Record<string, unknown>;
      const label = candidate.label || candidate.question || candidate.name || candidate.id;
      if (typeof label === 'string') return label;
    }
    return JSON.stringify(field);
  });
}

export default function ApplicationsPage() {
  const [applications, setApplications] = useState<Application[]>([]);
  const [userId, setUserId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<ApplicationFilter>('all');

  const loadApplications = useCallback(async (ownerId: string) => {
    const { data, error: queryError } = await supabase
      .from('applications')
      .select(APPLICATION_SELECT)
      .eq('user_id', ownerId)
      .order('updated_at', { ascending: false });

    if (queryError) {
      setError(queryError.message);
      return;
    }

    const validRows = ((data as unknown as Application[]) || []).filter((application) =>
      isApplicationStatus(application.status),
    );
    setApplications(validRows);
    setError(null);
  }, []);

  useEffect(() => {
    let disposed = false;
    let activeUserId: string | null = null;
    let channel: ReturnType<typeof supabase.channel> | null = null;

    async function start() {
      const { data: { user } } = await supabase.auth.getUser();
      if (disposed) return;

      if (!user) {
        setError('Sign in again to load your applications.');
        setLoading(false);
        return;
      }

      activeUserId = user.id;
      setUserId(user.id);
      await loadApplications(user.id);
      if (disposed) return;
      setLoading(false);

      channel = supabase
        .channel(`applications-${user.id}`)
        .on(
          'postgres_changes',
          {
            event: '*',
            schema: 'public',
            table: 'applications',
            filter: `user_id=eq.${user.id}`,
          },
          () => void loadApplications(user.id),
        )
        .subscribe();
    }

    function refreshOnFocus() {
      if (activeUserId) void loadApplications(activeUserId);
    }

    void start();
    window.addEventListener('focus', refreshOnFocus);

    return () => {
      disposed = true;
      window.removeEventListener('focus', refreshOnFocus);
      if (channel) void supabase.removeChannel(channel);
    };
  }, [loadApplications]);

  const filteredApplications = useMemo(() => {
    const query = search.trim().toLowerCase();
    return applications.filter((application) => {
      if (filter !== 'all' && APPLICATION_STATUS_META[application.status].group !== filter) return false;
      if (!query) return true;

      const job = application.jobs;
      return [job?.title, job?.companies?.name, job?.location, application.adapter, application.status]
        .some((value) => value?.toLowerCase().includes(query));
    });
  }, [applications, filter, search]);

  const counts = useMemo(() => {
    const result: Record<ApplicationStatusGroup, number> = {
      attention: 0,
      processing: 0,
      active: 0,
      closed: 0,
    };
    applications.forEach((application) => {
      result[APPLICATION_STATUS_META[application.status].group] += 1;
    });
    return result;
  }, [applications]);

  async function refresh() {
    if (!userId) return;
    setRefreshing(true);
    await loadApplications(userId);
    setRefreshing(false);
  }

  async function updateApplication(
    application: Application,
    values: Partial<Pick<Application, 'status' | 'last_error' | 'queued_at' | 'submitted_at'>>,
  ) {
    if (!userId || updatingId) return;
    setUpdatingId(application.id);
    setError(null);

    const updatedAt = new Date().toISOString();
    const { data, error: updateError } = await supabase
      .from('applications')
      .update({ ...values, updated_at: updatedAt })
      .eq('id', application.id)
      .eq('user_id', userId)
      // Avoid overwriting a newer state if the worker advanced it between refreshes.
      .eq('status', application.status)
      .select('id')
      .maybeSingle();

    if (updateError) {
      setError(updateError.message);
    } else if (!data) {
      setError('This application changed in the background. It has been refreshed.');
      await loadApplications(userId);
    } else {
      setApplications((current) => current.map((item) => (
        item.id === application.id ? { ...item, ...values, updated_at: updatedAt } : item
      )));
    }

    setUpdatingId(null);
  }

  async function authorizeSubmission(application: Application) {
    if (!userId || updatingId || !application.form_fingerprint) return;
    setUpdatingId(application.id);
    setError(null);
    const { error: authorizationError } = await supabase.rpc(
      'authorize_application_submission',
      {
        p_application_id: application.id,
        p_form_fingerprint: application.form_fingerprint,
      },
    );
    if (authorizationError) setError(authorizationError.message);
    await loadApplications(userId);
    setUpdatingId(null);
  }

  function applicationActions(application: Application) {
    const busy = updatingId === application.id;
    const now = () => new Date().toISOString();
    const retry = () => updateApplication(application, {
      status: 'queued',
      queued_at: now(),
      last_error: null,
    });
    const markSubmitted = () => updateApplication(application, {
      status: 'submitted',
      submitted_at: now(),
    });

    switch (application.status) {
      case 'queued':
        return (
          <button className="btn btn-secondary btn-compact" disabled={busy} onClick={() => updateApplication(application, { status: 'skipped' })}>
            Skip
          </button>
        );
      case 'needs_review':
        return (
          <button className="btn btn-secondary btn-compact" disabled={busy} onClick={() => updateApplication(application, { status: 'skipped' })}>
            Skip
          </button>
        );
      case 'ready_to_submit':
        return (
          <>
            <button className="btn btn-compact" disabled={busy || !application.form_fingerprint} onClick={() => authorizeSubmission(application)}>
              Authorize worker (30 min)
            </button>
            <button className="btn btn-secondary btn-compact" disabled={busy} onClick={markSubmitted}>
              I submitted manually
            </button>
          </>
        );
      case 'submission_unknown':
        return (
          <button className="btn btn-compact" disabled={busy} onClick={markSubmitted}>
            Confirm submitted
          </button>
        );
      case 'failed':
        return (
          <>
            <button className="btn btn-compact" disabled={busy} onClick={retry}>Retry</button>
            <button className="btn btn-secondary btn-compact" disabled={busy} onClick={() => updateApplication(application, { status: 'skipped' })}>
              Skip
            </button>
          </>
        );
      case 'submitted':
        return (
          <>
            <button className="btn btn-secondary btn-compact" disabled={busy} onClick={() => updateApplication(application, { status: 'assessment' })}>
              Assessment
            </button>
            <button className="btn btn-secondary btn-compact" disabled={busy} onClick={() => updateApplication(application, { status: 'interview' })}>
              Interview
            </button>
            <button className="btn btn-secondary btn-compact" disabled={busy} onClick={() => updateApplication(application, { status: 'rejected' })}>
              Rejected
            </button>
            <button className="btn btn-secondary btn-compact" disabled={busy} onClick={() => updateApplication(application, { status: 'withdrawn' })}>
              Withdrawn
            </button>
          </>
        );
      case 'assessment':
        return (
          <>
            <button className="btn btn-compact" disabled={busy} onClick={() => updateApplication(application, { status: 'interview' })}>
              Move to interview
            </button>
            <button className="btn btn-secondary btn-compact" disabled={busy} onClick={() => updateApplication(application, { status: 'rejected' })}>
              Rejected
            </button>
            <button className="btn btn-secondary btn-compact" disabled={busy} onClick={() => updateApplication(application, { status: 'withdrawn' })}>
              Withdrawn
            </button>
          </>
        );
      case 'interview':
        return (
          <>
            <button className="btn btn-compact" disabled={busy} onClick={() => updateApplication(application, { status: 'offer' })}>
              Mark offer
            </button>
            <button className="btn btn-secondary btn-compact" disabled={busy} onClick={() => updateApplication(application, { status: 'rejected' })}>
              Rejected
            </button>
            <button className="btn btn-secondary btn-compact" disabled={busy} onClick={() => updateApplication(application, { status: 'withdrawn' })}>
              Withdrawn
            </button>
          </>
        );
      default:
        return null;
    }
  }

  if (loading) {
    return <p className="subtitle">Loading applications...</p>;
  }

  return (
    <div>
      <div className="page-heading-row">
        <div>
          <h1 className="title text-gradient">Applications</h1>
          <p className="subtitle">Review the autofill queue and track every application through its outcome.</p>
        </div>
        <button className="btn btn-secondary" onClick={refresh} disabled={refreshing || !userId}>
          {refreshing ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {error && <div className="notice notice-error" role="alert">{error}</div>}

      <div className="application-stats" aria-label="Application summary">
        {APPLICATION_GROUPS.map((group) => (
          <button
            type="button"
            className={`stat-card${filter === group.id ? ' is-selected' : ''}`}
            key={group.id}
            onClick={() => setFilter(filter === group.id ? 'all' : group.id)}
          >
            <span>{group.label}</span>
            <strong>{counts[group.id]}</strong>
          </button>
        ))}
      </div>

      <div className="card application-filters">
        <div className="input-group">
          <label htmlFor="application-search">Search applications</label>
          <input
            id="application-search"
            className="input-field"
            placeholder="Title, company, location, or ATS..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div className="input-group">
          <label htmlFor="application-filter">Stage</label>
          <select
            id="application-filter"
            className="input-field"
            value={filter}
            onChange={(event) => setFilter(event.target.value as ApplicationFilter)}
          >
            <option value="all">All stages</option>
            {APPLICATION_GROUPS.map((group) => (
              <option key={group.id} value={group.id}>{group.label}</option>
            ))}
          </select>
        </div>
      </div>

      {applications.length === 0 ? (
        <div className="card empty-state">
          <h2>No applications queued yet</h2>
          <p>Start with a high-scoring match, then the worker can inspect and autofill its application form.</p>
          <Link href="/dashboard/matches" className="btn">Browse job matches</Link>
        </div>
      ) : (
        <div className="application-groups">
          {APPLICATION_GROUPS.filter((group) => filter === 'all' || filter === group.id).map((group) => {
            const groupApplications = filteredApplications.filter(
              (application) => APPLICATION_STATUS_META[application.status].group === group.id,
            );
            if (groupApplications.length === 0) return null;

            return (
              <section key={group.id} aria-labelledby={`application-group-${group.id}`}>
                <div className="section-heading-row">
                  <div>
                    <h2 id={`application-group-${group.id}`}>{group.label}</h2>
                    <p>{group.description}</p>
                  </div>
                  <span className="count-badge">{groupApplications.length}</span>
                </div>

                <div className="grid">
                  {groupApplications.map((application) => {
                    const job = application.jobs;
                    const company = job?.companies;
                    const unknownFields = unknownFieldLabels(application.unknown_fields);
                    const applicationUrl = application.target_url || job?.url;
                    const events = [...(application.application_events || [])]
                      .sort((left, right) => right.created_at.localeCompare(left.created_at));

                    return (
                      <article className="card application-card" key={application.id}>
                        <div className="application-card-main">
                          <img
                            src={company?.favicon_url || `${basePath}/file.svg`}
                            alt=""
                            className="company-favicon"
                            onError={(event) => { (event.currentTarget as HTMLImageElement).src = `${basePath}/file.svg`; }}
                          />
                          <div className="application-card-copy">
                            <div className="application-card-title-row">
                              <div>
                                <h3>{job?.title || 'Unavailable job'}</h3>
                                <p>
                                  {company?.name || 'Unknown company'}
                                  {job?.location ? ` — ${job.location}` : ''}
                                </p>
                              </div>
                              <ApplicationStatusBadge status={application.status} />
                            </div>

                            <div className="application-meta">
                              <span>{humanize(application.mode)}</span>
                              <span>{application.adapter ? humanize(application.adapter) : 'ATS pending'}</span>
                              <span>Updated {formatTimestamp(application.updated_at)}</span>
                            </div>

                            {application.last_error && (
                              <div className="notice notice-error application-notice" role="alert">
                                {application.last_error}
                              </div>
                            )}

                            {unknownFields.length > 0 && (
                              <div className="review-fields">
                                <strong>Questions to review</strong>
                                <ul>
                                  {unknownFields.map((field, index) => <li key={`${field}-${index}`}>{field}</li>)}
                                </ul>
                              </div>
                            )}

                            {application.status === 'needs_review' && userId && (
                              <ApplicationAnswerReview
                                applicationId={application.id}
                                userId={userId}
                                formSnapshot={application.form_snapshot}
                                unknownFields={application.unknown_fields}
                                answersSnapshot={application.answers_snapshot}
                                onSaved={() => loadApplications(userId)}
                              />
                            )}

                            <div className="application-actions">
                              {applicationUrl && (
                                <a className="btn btn-secondary btn-compact" href={applicationUrl} target="_blank" rel="noreferrer">
                                  Open application ↗
                                </a>
                              )}
                              {application.confirmation_url && (
                                <a className="btn btn-secondary btn-compact" href={application.confirmation_url} target="_blank" rel="noreferrer">
                                  View confirmation ↗
                                </a>
                              )}
                              {applicationActions(application)}
                            </div>

                            <details className="application-details">
                              <summary>Run details</summary>
                              <dl>
                                <div><dt>Status</dt><dd>{APPLICATION_STATUS_META[application.status].description}</dd></div>
                                <div><dt>Queued</dt><dd>{formatTimestamp(application.queued_at)}</dd></div>
                                <div><dt>Submitted</dt><dd>{formatTimestamp(application.submitted_at)}</dd></div>
                                <div><dt>Confirmation</dt><dd>{application.confirmation_id || 'Not captured'}</dd></div>
                                <div><dt>Form fingerprint</dt><dd>{application.form_fingerprint || 'Not inspected'}</dd></div>
                                <div><dt>Evidence</dt><dd>{application.evidence_path || 'Not captured'}</dd></div>
                              </dl>
                              {events.length > 0 && (
                                <div className="application-timeline">
                                  <h4>History</h4>
                                  <ol>
                                    {events.map((event) => (
                                      <li key={event.id}>
                                        <div>
                                          <strong>
                                            {event.from_status && event.to_status
                                              ? `${humanize(event.from_status)} → ${humanize(event.to_status)}`
                                              : humanize(event.to_status || event.event_type)}
                                          </strong>
                                          <span>{formatTimestamp(event.created_at)}</span>
                                        </div>
                                        <p>{event.message || `Recorded by ${humanize(event.actor)}`}</p>
                                      </li>
                                    ))}
                                  </ol>
                                </div>
                              )}
                            </details>
                          </div>
                        </div>
                      </article>
                    );
                  })}
                </div>
              </section>
            );
          })}

          {filteredApplications.length === 0 && (
            <div className="card empty-state">
              <h2>No applications match</h2>
              <p>Try another search or clear the stage filter.</p>
              <button type="button" className="btn btn-secondary" onClick={() => { setSearch(''); setFilter('all'); }}>
                Clear filters
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
