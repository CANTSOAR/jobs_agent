'use client';

import { useEffect, useState } from 'react';
import { supabase } from '@/lib/supabaseClient';

interface RunRequest {
  id: string;
  status: string;
  request_type: string;
  requested_at: string;
}

interface ApplicationProfileForm {
  first_name: string;
  last_name: string;
  preferred_name: string;
  email: string;
  phone: string;
  address_line_1: string;
  address_line_2: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
  linkedin_url: string;
  github_url: string;
  portfolio_url: string;
  school: string;
  degree: string;
  major: string;
  graduation_month: string;
  graduation_year: string;
  work_authorization: string;
  requires_sponsorship: '' | 'yes' | 'no';
}

interface JobPreferencesForm {
  target_categories: string;
  target_terms: string;
  preferred_locations: string;
  excluded_title_keywords: string;
  allow_remote: boolean;
  willing_to_relocate: boolean;
  min_match_score: string;
}

type ApplicationMode = 'track_only' | 'inspect' | 'autofill' | 'auto_submit_if_safe';

interface ApplicationPolicyForm {
  default_mode: ApplicationMode;
  min_match_score: string;
  ats_allowlist: string;
  company_allowlist: string;
  max_daily_submissions: string;
  auto_submit_authorized: boolean;
}

const EMPTY_APPLICATION_PROFILE: ApplicationProfileForm = {
  first_name: '',
  last_name: '',
  preferred_name: '',
  email: '',
  phone: '',
  address_line_1: '',
  address_line_2: '',
  city: '',
  state: '',
  postal_code: '',
  country: '',
  linkedin_url: '',
  github_url: '',
  portfolio_url: '',
  school: '',
  degree: '',
  major: '',
  graduation_month: '',
  graduation_year: '',
  work_authorization: '',
  requires_sponsorship: '',
};

const EMPTY_JOB_PREFERENCES: JobPreferencesForm = {
  target_categories: '',
  target_terms: '',
  preferred_locations: '',
  excluded_title_keywords: '',
  allow_remote: true,
  willing_to_relocate: false,
  min_match_score: '70',
};

const EMPTY_APPLICATION_POLICY: ApplicationPolicyForm = {
  default_mode: 'track_only',
  min_match_score: '85',
  ats_allowlist: 'greenhouse',
  company_allowlist: '',
  max_daily_submissions: '3',
  auto_submit_authorized: false,
};

const AUTO_SUBMIT_CONFIRMATION = 'ENABLE GUARDED AUTO SUBMIT';

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function storedString(record: Record<string, unknown>, key: string) {
  return typeof record[key] === 'string' ? record[key] as string : '';
}

function storedList(record: Record<string, unknown>, key: string) {
  return Array.isArray(record[key])
    ? (record[key] as unknown[]).filter((item): item is string => typeof item === 'string').join(', ')
    : '';
}

function parseList(value: string) {
  return Array.from(new Set(value.split(',').map((item) => item.trim()).filter(Boolean)));
}

export default function DashboardProfile() {
  const [userId, setUserId] = useState<string | null>(null);
  const [resumeText, setResumeText] = useState('');
  const [goalDescription, setGoalDescription] = useState('');
  const [loading, setLoading] = useState(true);
  const [savingResume, setSavingResume] = useState(false);
  const [savingGoals, setSavingGoals] = useState(false);
  const [runRequests, setRunRequests] = useState<RunRequest[]>([]);
  const [requestingRun, setRequestingRun] = useState(false);
  const [requestingMatches, setRequestingMatches] = useState(false);
  const [emailNotifications, setEmailNotifications] = useState(true);
  const [applicationProfile, setApplicationProfile] = useState<ApplicationProfileForm>(EMPTY_APPLICATION_PROFILE);
  const [jobPreferences, setJobPreferences] = useState<JobPreferencesForm>(EMPTY_JOB_PREFERENCES);
  const [savingApplicationProfile, setSavingApplicationProfile] = useState(false);
  const [savingJobPreferences, setSavingJobPreferences] = useState(false);
  const [applicationPolicy, setApplicationPolicy] = useState<ApplicationPolicyForm>(EMPTY_APPLICATION_POLICY);
  const [autoSubmitConfirmation, setAutoSubmitConfirmation] = useState('');
  const [savingApplicationPolicy, setSavingApplicationPolicy] = useState(false);

  useEffect(() => {
    (async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) {
        setLoading(false);
        return;
      }
      setUserId(user.id);

      const [{ data }, { data: runs }, { data: storedPolicy }] = await Promise.all([
        supabase
          .from('profiles')
          .select('resume_text, goal_description, email_notifications_enabled, application_profile, job_preferences')
          .eq('id', user.id)
          .single(),
        supabase.from('run_requests').select('id, status, request_type, requested_at').order('requested_at', { ascending: false }).limit(5),
        supabase
          .from('application_policies')
          .select('default_mode, min_match_score, ats_allowlist, company_allowlist, max_daily_submissions, auto_submit_authorized')
          .eq('user_id', user.id)
          .maybeSingle(),
      ]);

      if (data) {
        setResumeText(data.resume_text || '');
        setGoalDescription(data.goal_description || '');
        setEmailNotifications(data.email_notifications_enabled ?? true);

        const storedProfile = asRecord(data.application_profile);
        setApplicationProfile({
          first_name: storedString(storedProfile, 'first_name'),
          last_name: storedString(storedProfile, 'last_name'),
          preferred_name: storedString(storedProfile, 'preferred_name'),
          email: storedString(storedProfile, 'email') || user.email || '',
          phone: storedString(storedProfile, 'phone'),
          address_line_1: storedString(storedProfile, 'address_line_1'),
          address_line_2: storedString(storedProfile, 'address_line_2'),
          city: storedString(storedProfile, 'city'),
          state: storedString(storedProfile, 'state'),
          postal_code: storedString(storedProfile, 'postal_code'),
          country: storedString(storedProfile, 'country'),
          linkedin_url: storedString(storedProfile, 'linkedin_url'),
          github_url: storedString(storedProfile, 'github_url'),
          portfolio_url: storedString(storedProfile, 'portfolio_url'),
          school: storedString(storedProfile, 'school'),
          degree: storedString(storedProfile, 'degree'),
          major: storedString(storedProfile, 'major'),
          graduation_month: storedString(storedProfile, 'graduation_month'),
          graduation_year: storedString(storedProfile, 'graduation_year'),
          work_authorization: storedString(storedProfile, 'work_authorization'),
          requires_sponsorship: typeof storedProfile.requires_sponsorship === 'boolean'
            ? storedProfile.requires_sponsorship ? 'yes' : 'no'
            : '',
        });

        const storedPreferences = asRecord(data.job_preferences);
        setJobPreferences({
          target_categories: storedList(storedPreferences, 'target_categories'),
          target_terms: storedList(storedPreferences, 'target_terms'),
          preferred_locations: storedList(storedPreferences, 'preferred_locations'),
          excluded_title_keywords: storedList(storedPreferences, 'excluded_title_keywords'),
          allow_remote: typeof storedPreferences.allow_remote === 'boolean' ? storedPreferences.allow_remote : true,
          willing_to_relocate: typeof storedPreferences.willing_to_relocate === 'boolean' ? storedPreferences.willing_to_relocate : false,
          min_match_score: typeof storedPreferences.min_match_score === 'number'
            ? String(storedPreferences.min_match_score)
            : '70',
        });
      }
      if (storedPolicy) {
        setApplicationPolicy({
          default_mode: storedPolicy.default_mode as ApplicationMode,
          min_match_score: String(storedPolicy.min_match_score ?? 85),
          ats_allowlist: Array.isArray(storedPolicy.ats_allowlist) ? storedPolicy.ats_allowlist.join(', ') : 'greenhouse',
          company_allowlist: Array.isArray(storedPolicy.company_allowlist) ? storedPolicy.company_allowlist.join(', ') : '',
          max_daily_submissions: String(storedPolicy.max_daily_submissions ?? 3),
          auto_submit_authorized: Boolean(storedPolicy.auto_submit_authorized),
        });
      }
      setRunRequests(runs || []);
      setLoading(false);
    })();
  }, []);

  async function toggleEmailNotifications() {
    if (!userId) return;
    const next = !emailNotifications;
    setEmailNotifications(next);
    const { error } = await supabase
      .from('profiles')
      .upsert({ id: userId, email_notifications_enabled: next }, { onConflict: 'id' });
    if (error) {
      alert(error.message);
      setEmailNotifications(!next);
    }
  }

  async function refreshRunRequests() {
    const { data: runs } = await supabase
      .from('run_requests')
      .select('id, status, request_type, requested_at')
      .order('requested_at', { ascending: false })
      .limit(5);
    setRunRequests(runs || []);
  }

  async function requestRun() {
    if (!userId) return;
    setRequestingRun(true);
    const { error } = await supabase.from('run_requests').insert({ requested_by: userId, request_type: 'full' });
    if (error) alert(error.message);
    else await refreshRunRequests();
    setRequestingRun(false);
  }

  async function requestMatches() {
    if (!userId) return;
    setRequestingMatches(true);
    const { error } = await supabase.from('run_requests').insert({ requested_by: userId, request_type: 'evaluate_only' });
    if (error) alert(error.message);
    else await refreshRunRequests();
    setRequestingMatches(false);
  }

  async function saveResume() {
    if (!userId) return;
    setSavingResume(true);
    const { error } = await supabase
      .from('profiles')
      .upsert({ id: userId, resume_text: resumeText }, { onConflict: 'id' });
    if (error) alert(error.message);
    setSavingResume(false);
  }

  async function saveGoals() {
    if (!userId) return;
    setSavingGoals(true);
    const { error } = await supabase
      .from('profiles')
      .upsert({ id: userId, goal_description: goalDescription }, { onConflict: 'id' });
    if (error) alert(error.message);
    setSavingGoals(false);
  }

  async function saveApplicationProfile() {
    if (!userId) return;
    setSavingApplicationProfile(true);
    const payload = {
      ...applicationProfile,
      requires_sponsorship: applicationProfile.requires_sponsorship === ''
        ? null
        : applicationProfile.requires_sponsorship === 'yes',
    };
    const { error } = await supabase
      .from('profiles')
      .upsert({ id: userId, application_profile: payload }, { onConflict: 'id' });
    if (error) alert(error.message);
    setSavingApplicationProfile(false);
  }

  async function saveJobPreferences() {
    if (!userId) return;
    setSavingJobPreferences(true);
    const parsedScore = Number(jobPreferences.min_match_score);
    const payload = {
      target_categories: parseList(jobPreferences.target_categories),
      target_terms: parseList(jobPreferences.target_terms),
      preferred_locations: parseList(jobPreferences.preferred_locations),
      excluded_title_keywords: parseList(jobPreferences.excluded_title_keywords),
      allow_remote: jobPreferences.allow_remote,
      willing_to_relocate: jobPreferences.willing_to_relocate,
      min_match_score: Number.isFinite(parsedScore) ? Math.min(100, Math.max(0, parsedScore)) : 0,
    };
    const { error } = await supabase
      .from('profiles')
      .upsert({ id: userId, job_preferences: payload }, { onConflict: 'id' });
    if (error) alert(error.message);
    setSavingJobPreferences(false);
  }

  async function saveApplicationPolicy() {
    if (!userId) return;
    const atsAllowlist = parseList(applicationPolicy.ats_allowlist).map((item) => item.toLowerCase());
    const companyAllowlist = parseList(applicationPolicy.company_allowlist);
    const autoSubmit = applicationPolicy.default_mode === 'auto_submit_if_safe'
      && applicationPolicy.auto_submit_authorized;

    if (autoSubmit && autoSubmitConfirmation !== AUTO_SUBMIT_CONFIRMATION) {
      alert(`Type ${AUTO_SUBMIT_CONFIRMATION} exactly before enabling unattended final submission.`);
      return;
    }
    if (autoSubmit && (atsAllowlist.length === 0 || companyAllowlist.length === 0)) {
      alert('Automatic final submission requires both an ATS adapter and an exact company allowlist.');
      return;
    }

    const parsedThreshold = Number(applicationPolicy.min_match_score);
    const parsedDailyLimit = Number(applicationPolicy.max_daily_submissions);
    setSavingApplicationPolicy(true);
    const { error } = await supabase
      .from('application_policies')
      .upsert({
        user_id: userId,
        default_mode: applicationPolicy.default_mode,
        min_match_score: Number.isFinite(parsedThreshold) ? Math.min(100, Math.max(0, parsedThreshold)) : 85,
        ats_allowlist: atsAllowlist,
        company_allowlist: companyAllowlist,
        max_daily_submissions: Number.isFinite(parsedDailyLimit) ? Math.min(20, Math.max(0, parsedDailyLimit)) : 3,
        require_review_on_unknown_question: true,
        auto_submit_authorized: autoSubmit,
        auto_submit_authorized_at: autoSubmit ? new Date().toISOString() : null,
      }, { onConflict: 'user_id' });
    if (error) alert(error.message);
    else setAutoSubmitConfirmation('');
    setSavingApplicationPolicy(false);
  }

  function updateApplicationProfile<K extends keyof ApplicationProfileForm>(
    key: K,
    value: ApplicationProfileForm[K],
  ) {
    setApplicationProfile((current) => ({ ...current, [key]: value }));
  }

  function updateJobPreferences<K extends keyof JobPreferencesForm>(
    key: K,
    value: JobPreferencesForm[K],
  ) {
    setJobPreferences((current) => ({ ...current, [key]: value }));
  }

  function updateApplicationPolicy<K extends keyof ApplicationPolicyForm>(
    key: K,
    value: ApplicationPolicyForm[K],
  ) {
    setApplicationPolicy((current) => ({ ...current, [key]: value }));
  }

  if (loading) {
    return <p className="subtitle">Loading profile...</p>;
  }

  return (
    <div>
      <h1 className="title text-gradient">Profile & Goals</h1>
      <p className="subtitle">Paste your resume and tell the agent what you&apos;re looking for.</p>

      <div className="card" style={{ marginBottom: '2.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: runRequests.length > 0 ? '1rem' : 0 }}>
          <div>
            <h2 style={{ marginBottom: '0.25rem' }}>Agent Control</h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
              The agent normally runs on whatever schedule you&apos;ve set up. Request an extra run any time.
            </p>
          </div>
          <div style={{ display: 'flex', gap: '0.75rem', flexShrink: 0 }}>
            <button className="btn btn-secondary" onClick={requestMatches} disabled={requestingMatches}>
              {requestingMatches ? 'Requesting...' : 'Find My Matches Now'}
            </button>
            <button className="btn" onClick={requestRun} disabled={requestingRun}>
              {requestingRun ? 'Requesting...' : 'Run Agent Now'}
            </button>
          </div>
        </div>
        {runRequests.length > 0 && (
          <ul style={{ listStyle: 'none', display: 'grid', gap: '0.5rem', marginBottom: '1rem' }}>
            {runRequests.map(r => (
              <li key={r.id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                <span>{new Date(r.requested_at).toLocaleString()} — {r.request_type === 'evaluate_only' ? 'find matches' : 'full run'}</span>
                <span className={`status-badge status-${r.status}`}>{r.status}</span>
              </li>
            ))}
          </ul>
        )}
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.9rem' }}>
          <input type="checkbox" checked={emailNotifications} onChange={toggleEmailNotifications} />
          Email me when the agent finds a strong job match
        </label>
      </div>

      <div className="grid grid-cols-2" style={{ marginBottom: '2.5rem' }}>
        <div className="card">
          <h2 style={{ marginBottom: '1rem' }}>Resume</h2>
          <div className="input-group">
            <label>Paste your resume text</label>
            <textarea
              className="input-field textarea-field"
              placeholder="Paste your resume content here..."
              value={resumeText}
              onChange={e => setResumeText(e.target.value)}
            />
          </div>
          <button className="btn" onClick={saveResume} disabled={savingResume}>
            {savingResume ? 'Saving...' : 'Save Resume'}
          </button>
        </div>

        <div className="card">
          <h2 style={{ marginBottom: '1rem' }}>Career Goals</h2>
          <div className="input-group">
            <label>What exactly are you looking for?</label>
            <textarea
              className="input-field textarea-field"
              placeholder="e.g. Senior Frontend Engineer, remote, $150k+ base, Next.js focused..."
              value={goalDescription}
              onChange={e => setGoalDescription(e.target.value)}
            />
          </div>
          <button className="btn" onClick={saveGoals} disabled={savingGoals}>
            {savingGoals ? 'Saving...' : 'Save Goals'}
          </button>
        </div>
      </div>

      <section style={{ marginBottom: '2.5rem' }}>
        <h2 style={{ marginBottom: '0.5rem' }}>Application Profile</h2>
        <p className="subtitle" style={{ fontSize: '1rem', marginBottom: '1rem' }}>
          These are the only personal fields the autofill worker may reuse. Leave anything unknown blank.
        </p>
        <div className="card profile-form">
          <fieldset>
            <legend>Contact</legend>
            <div className="profile-form-grid">
              <div className="input-group">
                <label htmlFor="profile-first-name">First name</label>
                <input id="profile-first-name" className="input-field" value={applicationProfile.first_name} onChange={(event) => updateApplicationProfile('first_name', event.target.value)} />
              </div>
              <div className="input-group">
                <label htmlFor="profile-last-name">Last name</label>
                <input id="profile-last-name" className="input-field" value={applicationProfile.last_name} onChange={(event) => updateApplicationProfile('last_name', event.target.value)} />
              </div>
              <div className="input-group">
                <label htmlFor="profile-preferred-name">Preferred name</label>
                <input id="profile-preferred-name" className="input-field" value={applicationProfile.preferred_name} onChange={(event) => updateApplicationProfile('preferred_name', event.target.value)} />
              </div>
              <div className="input-group">
                <label htmlFor="profile-email">Application email</label>
                <input id="profile-email" type="email" className="input-field" value={applicationProfile.email} onChange={(event) => updateApplicationProfile('email', event.target.value)} />
              </div>
              <div className="input-group">
                <label htmlFor="profile-phone">Phone</label>
                <input id="profile-phone" type="tel" className="input-field" value={applicationProfile.phone} onChange={(event) => updateApplicationProfile('phone', event.target.value)} />
              </div>
            </div>
          </fieldset>

          <fieldset>
            <legend>Address</legend>
            <div className="profile-form-grid">
              <div className="input-group profile-span-2">
                <label htmlFor="profile-address-1">Address line 1</label>
                <input id="profile-address-1" className="input-field" value={applicationProfile.address_line_1} onChange={(event) => updateApplicationProfile('address_line_1', event.target.value)} />
              </div>
              <div className="input-group">
                <label htmlFor="profile-address-2">Address line 2</label>
                <input id="profile-address-2" className="input-field" value={applicationProfile.address_line_2} onChange={(event) => updateApplicationProfile('address_line_2', event.target.value)} />
              </div>
              <div className="input-group">
                <label htmlFor="profile-city">City</label>
                <input id="profile-city" className="input-field" value={applicationProfile.city} onChange={(event) => updateApplicationProfile('city', event.target.value)} />
              </div>
              <div className="input-group">
                <label htmlFor="profile-state">State / region</label>
                <input id="profile-state" className="input-field" value={applicationProfile.state} onChange={(event) => updateApplicationProfile('state', event.target.value)} />
              </div>
              <div className="input-group">
                <label htmlFor="profile-postal-code">Postal code</label>
                <input id="profile-postal-code" className="input-field" value={applicationProfile.postal_code} onChange={(event) => updateApplicationProfile('postal_code', event.target.value)} />
              </div>
              <div className="input-group">
                <label htmlFor="profile-country">Country</label>
                <input id="profile-country" className="input-field" value={applicationProfile.country} onChange={(event) => updateApplicationProfile('country', event.target.value)} />
              </div>
            </div>
          </fieldset>

          <fieldset>
            <legend>Links</legend>
            <div className="profile-form-grid">
              <div className="input-group">
                <label htmlFor="profile-linkedin">LinkedIn URL</label>
                <input id="profile-linkedin" type="url" className="input-field" value={applicationProfile.linkedin_url} onChange={(event) => updateApplicationProfile('linkedin_url', event.target.value)} />
              </div>
              <div className="input-group">
                <label htmlFor="profile-github">GitHub URL</label>
                <input id="profile-github" type="url" className="input-field" value={applicationProfile.github_url} onChange={(event) => updateApplicationProfile('github_url', event.target.value)} />
              </div>
              <div className="input-group">
                <label htmlFor="profile-portfolio">Portfolio URL</label>
                <input id="profile-portfolio" type="url" className="input-field" value={applicationProfile.portfolio_url} onChange={(event) => updateApplicationProfile('portfolio_url', event.target.value)} />
              </div>
            </div>
          </fieldset>

          <fieldset>
            <legend>Education</legend>
            <div className="profile-form-grid">
              <div className="input-group">
                <label htmlFor="profile-school">School</label>
                <input id="profile-school" className="input-field" value={applicationProfile.school} onChange={(event) => updateApplicationProfile('school', event.target.value)} />
              </div>
              <div className="input-group">
                <label htmlFor="profile-degree">Degree</label>
                <input id="profile-degree" className="input-field" value={applicationProfile.degree} onChange={(event) => updateApplicationProfile('degree', event.target.value)} />
              </div>
              <div className="input-group">
                <label htmlFor="profile-major">Major</label>
                <input id="profile-major" className="input-field" value={applicationProfile.major} onChange={(event) => updateApplicationProfile('major', event.target.value)} />
              </div>
              <div className="input-group">
                <label htmlFor="profile-graduation-month">Graduation month</label>
                <input id="profile-graduation-month" className="input-field" placeholder="May" value={applicationProfile.graduation_month} onChange={(event) => updateApplicationProfile('graduation_month', event.target.value)} />
              </div>
              <div className="input-group">
                <label htmlFor="profile-graduation-year">Graduation year</label>
                <input id="profile-graduation-year" inputMode="numeric" className="input-field" placeholder="2027" value={applicationProfile.graduation_year} onChange={(event) => updateApplicationProfile('graduation_year', event.target.value)} />
              </div>
            </div>
          </fieldset>

          <fieldset className="sensitive-fieldset">
            <legend>Work authorization</legend>
            <p className="field-help">
              These answers are sensitive and application-specific. Set them only when you are certain; blank means the worker must ask you.
            </p>
            <div className="profile-form-grid">
              <div className="input-group">
                <label htmlFor="profile-work-authorization">Authorization status</label>
                <input
                  id="profile-work-authorization"
                  className="input-field"
                  placeholder="Leave blank if uncertain"
                  value={applicationProfile.work_authorization}
                  onChange={(event) => updateApplicationProfile('work_authorization', event.target.value)}
                />
              </div>
              <div className="input-group">
                <label htmlFor="profile-sponsorship">Require employer sponsorship?</label>
                <select
                  id="profile-sponsorship"
                  className="input-field"
                  value={applicationProfile.requires_sponsorship}
                  onChange={(event) => updateApplicationProfile('requires_sponsorship', event.target.value as ApplicationProfileForm['requires_sponsorship'])}
                >
                  <option value="">Unknown — always ask me</option>
                  <option value="yes">Yes</option>
                  <option value="no">No</option>
                </select>
              </div>
            </div>
          </fieldset>

          <button className="btn" onClick={saveApplicationProfile} disabled={savingApplicationProfile}>
            {savingApplicationProfile ? 'Saving...' : 'Save Application Profile'}
          </button>
        </div>
      </section>

      <section style={{ marginBottom: '2.5rem' }}>
        <h2 style={{ marginBottom: '0.5rem' }}>Job Preferences</h2>
        <p className="subtitle" style={{ fontSize: '1rem', marginBottom: '1rem' }}>
          Comma-separated lists help the matcher focus the feed. Blank lists do not create a hard filter.
        </p>
        <div className="card profile-form">
          <div className="profile-form-grid">
            <div className="input-group">
              <label htmlFor="preferences-categories">Target categories</label>
              <input
                id="preferences-categories"
                className="input-field"
                placeholder="software engineering, quantitative development"
                value={jobPreferences.target_categories}
                onChange={(event) => updateJobPreferences('target_categories', event.target.value)}
              />
            </div>
            <div className="input-group">
              <label htmlFor="preferences-terms">Target terms or title phrases</label>
              <input
                id="preferences-terms"
                className="input-field"
                placeholder="Summer 2027, software engineer intern"
                value={jobPreferences.target_terms}
                onChange={(event) => updateJobPreferences('target_terms', event.target.value)}
              />
            </div>
            <div className="input-group">
              <label htmlFor="preferences-locations">Preferred locations</label>
              <input
                id="preferences-locations"
                className="input-field"
                placeholder="New York, New Jersey, Remote"
                value={jobPreferences.preferred_locations}
                onChange={(event) => updateJobPreferences('preferred_locations', event.target.value)}
              />
            </div>
            <div className="input-group">
              <label htmlFor="preferences-excluded-titles">Excluded title keywords</label>
              <input
                id="preferences-excluded-titles"
                className="input-field"
                placeholder="senior, staff, principal"
                value={jobPreferences.excluded_title_keywords}
                onChange={(event) => updateJobPreferences('excluded_title_keywords', event.target.value)}
              />
            </div>
            <div className="input-group">
              <label htmlFor="preferences-min-score">Minimum match score</label>
              <input
                id="preferences-min-score"
                type="number"
                min="0"
                max="100"
                className="input-field"
                value={jobPreferences.min_match_score}
                onChange={(event) => updateJobPreferences('min_match_score', event.target.value)}
              />
            </div>
            <div className="checkbox-stack">
              <label>
                <input type="checkbox" checked={jobPreferences.allow_remote} onChange={(event) => updateJobPreferences('allow_remote', event.target.checked)} />
                Include remote roles
              </label>
              <label>
                <input type="checkbox" checked={jobPreferences.willing_to_relocate} onChange={(event) => updateJobPreferences('willing_to_relocate', event.target.checked)} />
                Willing to relocate
              </label>
            </div>
          </div>
          <button className="btn" onClick={saveJobPreferences} disabled={savingJobPreferences}>
            {savingJobPreferences ? 'Saving...' : 'Save Job Preferences'}
          </button>
        </div>
      </section>

      <section>
        <h2 style={{ marginBottom: '0.5rem' }}>Application Automation</h2>
        <p className="subtitle" style={{ fontSize: '1rem', marginBottom: '1rem' }}>
          Matching may queue work automatically. Final submission still requires the private worker&apos;s environment gate, these allowlists, and a form with no unresolved answers.
        </p>
        <div className="card profile-form">
          <div className="profile-form-grid">
            <div className="input-group">
              <label htmlFor="application-default-mode">Action for strong matches</label>
              <select
                id="application-default-mode"
                className="input-field"
                value={applicationPolicy.default_mode}
                onChange={(event) => updateApplicationPolicy('default_mode', event.target.value as ApplicationMode)}
              >
                <option value="track_only">Track only</option>
                <option value="inspect">Inspect form only</option>
                <option value="autofill">Autofill, then review</option>
                <option value="auto_submit_if_safe">Submit only when every guard passes</option>
              </select>
            </div>
            <div className="input-group">
              <label htmlFor="application-policy-score">Queue at match score</label>
              <input
                id="application-policy-score"
                type="number"
                min="0"
                max="100"
                className="input-field"
                value={applicationPolicy.min_match_score}
                onChange={(event) => updateApplicationPolicy('min_match_score', event.target.value)}
              />
            </div>
            <div className="input-group">
              <label htmlFor="application-ats-allowlist">Allowed ATS adapters</label>
              <input
                id="application-ats-allowlist"
                className="input-field"
                placeholder="greenhouse"
                value={applicationPolicy.ats_allowlist}
                onChange={(event) => updateApplicationPolicy('ats_allowlist', event.target.value)}
              />
              <span className="field-help">Currently supported for guarded live use: greenhouse. Generic forms remain review-first.</span>
            </div>
            <div className="input-group">
              <label htmlFor="application-company-allowlist">Exact company allowlist</label>
              <input
                id="application-company-allowlist"
                className="input-field"
                placeholder="Stripe, Datadog"
                value={applicationPolicy.company_allowlist}
                onChange={(event) => updateApplicationPolicy('company_allowlist', event.target.value)}
              />
            </div>
            <div className="input-group">
              <label htmlFor="application-daily-limit">Maximum final submissions per day</label>
              <input
                id="application-daily-limit"
                type="number"
                min="0"
                max="20"
                className="input-field"
                value={applicationPolicy.max_daily_submissions}
                onChange={(event) => updateApplicationPolicy('max_daily_submissions', event.target.value)}
              />
            </div>
          </div>

          {applicationPolicy.default_mode === 'auto_submit_if_safe' && (
            <fieldset className="sensitive-fieldset">
              <legend>Unattended final-submit consent</legend>
              <label className="policy-consent">
                <input
                  type="checkbox"
                  checked={applicationPolicy.auto_submit_authorized}
                  onChange={(event) => updateApplicationPolicy('auto_submit_authorized', event.target.checked)}
                />
                I authorize the private runner to submit only allowlisted, fully answered applications that pass every guard.
              </label>
              {applicationPolicy.auto_submit_authorized && (
                <div className="input-group">
                  <label htmlFor="application-auto-submit-confirmation">
                    Type <code>{AUTO_SUBMIT_CONFIRMATION}</code> to save this consent
                  </label>
                  <input
                    id="application-auto-submit-confirmation"
                    className="input-field"
                    value={autoSubmitConfirmation}
                    autoComplete="off"
                    onChange={(event) => setAutoSubmitConfirmation(event.target.value)}
                  />
                </div>
              )}
            </fieldset>
          )}

          <button className="btn" onClick={saveApplicationPolicy} disabled={savingApplicationPolicy}>
            {savingApplicationPolicy ? 'Saving...' : 'Save Automation Policy'}
          </button>
        </div>
      </section>
    </div>
  );
}
