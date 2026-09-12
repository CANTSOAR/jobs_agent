'use client';

import { useMemo, useState } from 'react';
import { supabase } from '@/lib/supabaseClient';

interface SnapshotField {
  key: string;
  label: string;
  kind: string;
  required?: boolean;
  options?: string[];
  sensitive?: boolean;
}

interface ApplicationAnswerReviewProps {
  applicationId: string;
  userId: string;
  formSnapshot: unknown;
  unknownFields: unknown;
  answersSnapshot: unknown;
  onSaved: () => void | Promise<void>;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringKeys(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : [];
}

function answerType(kind: string) {
  if (kind === 'checkbox') return 'boolean';
  if (kind === 'radio' || kind === 'select' || kind === 'combobox') return 'single_select';
  if (kind === 'multi_select') return 'multi_select';
  if (kind === 'number') return 'number';
  if (kind === 'date') return 'date';
  return 'text';
}

function typedValue(kind: string, value: string | string[]): string | string[] | number | boolean {
  if (kind === 'multi_select') return Array.isArray(value) ? value : [value];
  const scalar = Array.isArray(value) ? value[0] || '' : value;
  if (kind === 'checkbox') return scalar === 'true';
  if (kind === 'number') return Number(scalar);
  return scalar;
}

export function ApplicationAnswerReview({
  applicationId,
  userId,
  formSnapshot,
  unknownFields,
  answersSnapshot,
  onSaved,
}: ApplicationAnswerReviewProps) {
  const fields = useMemo(() => {
    const snapshot = record(formSnapshot);
    const answerData = record(answersSnapshot);
    const reviewKeys = new Set([
      ...stringKeys(unknownFields),
      ...stringKeys(answerData.review_keys),
    ]);
    const snapshotFields = Array.isArray(snapshot.fields) ? snapshot.fields : [];
    const seenKeys = new Set<string>();
    return snapshotFields
      .filter((item): item is SnapshotField => {
        const candidate = record(item);
        return typeof candidate.key === 'string'
          && typeof candidate.label === 'string'
          && typeof candidate.kind === 'string';
      })
      .filter((field) => {
        if (!reviewKeys.has(field.key) || seenKeys.has(field.key)) return false;
        seenKeys.add(field.key);
        return true;
      });
  }, [answersSnapshot, formSnapshot, unknownFields]);

  const [values, setValues] = useState<Record<string, string | string[]>>({});
  const [approved, setApproved] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (fields.length === 0) {
    return (
      <p className="field-help">
        No reusable answer field was detected. Open the application to handle a CAPTCHA, login, file, or validation issue manually.
      </p>
    );
  }

  async function saveAndRetry() {
    const incomplete = fields.find((field) => {
      const value = values[field.key];
      const hasValue = Array.isArray(value) ? value.length > 0 : Boolean(value?.trim());
      return !hasValue || !approved[field.key] || field.kind === 'file';
    });
    if (incomplete) {
      setError(
        incomplete.kind === 'file'
          ? 'Resume files must be configured on the private worker, not stored in the dashboard.'
          : `Enter and explicitly approve the answer for “${incomplete.label || incomplete.key}”.`,
      );
      return;
    }

    setSaving(true);
    setError(null);
    const payload = fields.map((field) => ({
      user_id: userId,
      key: field.key,
      question_pattern: field.label || field.key,
      answer_value: typedValue(field.kind, values[field.key] ?? ''),
      answer_type: answerType(field.kind),
      approved_for_autofill: true,
      approved_for_submission: true,
      is_sensitive: Boolean(field.sensitive),
    }));
    const { error: answerError } = await supabase
      .from('application_answers')
      .upsert(payload, { onConflict: 'user_id,key' });
    if (answerError) {
      setError(answerError.message);
      setSaving(false);
      return;
    }

    const { data, error: retryError } = await supabase
      .from('applications')
      .update({
        status: 'queued',
        queued_at: new Date().toISOString(),
        last_error: null,
      })
      .eq('id', applicationId)
      .eq('user_id', userId)
      .eq('status', 'needs_review')
      .select('id')
      .maybeSingle();

    if (retryError) setError(retryError.message);
    else if (!data) setError('The application changed in the background. Refresh and try again.');
    else await onSaved();
    setSaving(false);
  }

  return (
    <div className="answer-review">
      <strong>Provide explicit reusable answers</strong>
      <p className="field-help">
        These answers may be reused only for the same normalized question key. Each checkbox is explicit approval for guarded submission.
      </p>
      {fields.map((field) => {
        const options = Array.isArray(field.options) ? field.options.filter(Boolean) : [];
        return (
          <div className="answer-review-field" key={field.key}>
            <label htmlFor={`${applicationId}-${field.key}`}>
              {field.label || field.key}{field.sensitive ? ' (sensitive)' : ''}
            </label>
            {field.kind === 'checkbox' ? (
              <select
                id={`${applicationId}-${field.key}`}
                className="input-field"
                value={typeof values[field.key] === 'string' ? values[field.key] : ''}
                onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))}
              >
                <option value="">Choose...</option>
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            ) : field.kind === 'multi_select' && options.length > 0 ? (
              <>
                <select
                  id={`${applicationId}-${field.key}`}
                  className="input-field"
                  multiple
                  size={Math.min(7, Math.max(3, options.length))}
                  value={Array.isArray(values[field.key]) ? values[field.key] : []}
                  onChange={(event) => setValues((current) => ({
                    ...current,
                    [field.key]: Array.from(event.target.selectedOptions, (option) => option.value),
                  }))}
                >
                  {options.map((option) => <option value={option} key={option}>{option}</option>)}
                </select>
                <span className="field-help">Select every option that applies.</span>
              </>
            ) : options.length > 0 ? (
              <select
                id={`${applicationId}-${field.key}`}
                className="input-field"
                value={typeof values[field.key] === 'string' ? values[field.key] : ''}
                onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))}
              >
                <option value="">Choose...</option>
                {options.map((option) => <option value={option} key={option}>{option}</option>)}
              </select>
            ) : (
              <input
                id={`${applicationId}-${field.key}`}
                className="input-field"
                type={field.kind === 'number' ? 'number' : field.kind === 'date' ? 'date' : 'text'}
                value={typeof values[field.key] === 'string' ? values[field.key] : ''}
                disabled={field.kind === 'file'}
                onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))}
              />
            )}
            <label className="policy-consent">
              <input
                type="checkbox"
                checked={approved[field.key] || false}
                onChange={(event) => setApproved((current) => ({ ...current, [field.key]: event.target.checked }))}
              />
              I approve this exact answer for guarded final submission.
            </label>
          </div>
        );
      })}
      {error && <span className="inline-error" role="alert">{error}</span>}
      <button type="button" className="btn btn-compact" disabled={saving} onClick={saveAndRetry}>
        {saving ? 'Saving...' : 'Save answers & retry checks'}
      </button>
    </div>
  );
}
