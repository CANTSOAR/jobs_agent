export const APPLICATION_STATUSES = [
  'queued',
  'claimed',
  'inspected',
  'needs_review',
  'ready_to_submit',
  'submitting',
  'submitted',
  'submission_unknown',
  'assessment',
  'interview',
  'rejected',
  'offer',
  'withdrawn',
  'skipped',
  'failed',
] as const;

export type ApplicationStatus = (typeof APPLICATION_STATUSES)[number];

export type ApplicationStatusGroup = 'attention' | 'processing' | 'active' | 'closed';

interface ApplicationStatusMeta {
  label: string;
  description: string;
  group: ApplicationStatusGroup;
  tone: 'neutral' | 'info' | 'warning' | 'success' | 'danger';
}

export const APPLICATION_STATUS_META: Record<ApplicationStatus, ApplicationStatusMeta> = {
  queued: {
    label: 'Queued',
    description: 'Waiting for the application worker.',
    group: 'processing',
    tone: 'neutral',
  },
  claimed: {
    label: 'Claimed',
    description: 'A worker reserved this application.',
    group: 'processing',
    tone: 'info',
  },
  inspected: {
    label: 'Inspected',
    description: 'The application form was inspected successfully.',
    group: 'processing',
    tone: 'info',
  },
  needs_review: {
    label: 'Needs review',
    description: 'The form contains questions that need your answer.',
    group: 'attention',
    tone: 'warning',
  },
  ready_to_submit: {
    label: 'Ready to submit',
    description: 'The known fields are filled and the application is ready for final review.',
    group: 'attention',
    tone: 'info',
  },
  submitting: {
    label: 'Submitting',
    description: 'The worker is currently submitting this application.',
    group: 'processing',
    tone: 'info',
  },
  submitted: {
    label: 'Submitted',
    description: 'Submission evidence or confirmation was captured.',
    group: 'active',
    tone: 'success',
  },
  submission_unknown: {
    label: 'Check submission',
    description: 'The worker could not prove whether submission succeeded.',
    group: 'attention',
    tone: 'warning',
  },
  assessment: {
    label: 'Assessment',
    description: 'An assessment is pending or complete.',
    group: 'active',
    tone: 'info',
  },
  interview: {
    label: 'Interview',
    description: 'The application has reached the interview stage.',
    group: 'active',
    tone: 'info',
  },
  rejected: {
    label: 'Rejected',
    description: 'The employer closed the application without an offer.',
    group: 'closed',
    tone: 'danger',
  },
  offer: {
    label: 'Offer',
    description: 'An offer was received.',
    group: 'closed',
    tone: 'success',
  },
  withdrawn: {
    label: 'Withdrawn',
    description: 'You withdrew this application.',
    group: 'closed',
    tone: 'neutral',
  },
  skipped: {
    label: 'Skipped',
    description: 'This application was intentionally skipped.',
    group: 'closed',
    tone: 'neutral',
  },
  failed: {
    label: 'Failed',
    description: 'The worker stopped after an application error.',
    group: 'attention',
    tone: 'danger',
  },
};

export const APPLICATION_GROUPS: Array<{
  id: ApplicationStatusGroup;
  label: string;
  description: string;
}> = [
  { id: 'attention', label: 'Needs attention', description: 'Review, confirm, or retry these applications.' },
  { id: 'processing', label: 'In progress', description: 'The application worker is processing these.' },
  { id: 'active', label: 'Submitted', description: 'Applications still moving through the hiring process.' },
  { id: 'closed', label: 'Outcomes', description: 'Offers and closed applications.' },
];

export function isApplicationStatus(value: string): value is ApplicationStatus {
  return APPLICATION_STATUSES.includes(value as ApplicationStatus);
}
