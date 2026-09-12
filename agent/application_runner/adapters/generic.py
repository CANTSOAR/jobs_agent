from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from playwright.sync_api import Page

from ..models import (
    ApplicationForm,
    FieldKind,
    FillReport,
    FormField,
    ResolvedAnswers,
    SubmissionReceipt,
)
from ..policy import SENSITIVE_KEYS, canonical_key
from .base import ApplicationAdapter


_INSPECT_SCRIPT = r"""
() => {
  const ignoredTypes = new Set(['hidden', 'submit', 'button', 'reset', 'image']);
  const forms = Array.from(document.forms);
  if (!forms.length) return null;

  function isInspectable(el) {
    const type = (el.type || '').toLowerCase();
    if (el.disabled || ignoredTypes.has(type)) return false;
    // File controls are commonly visually hidden behind an Attach button.
    if (type === 'file') return true;
    if (!el.id && !el.name && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby')) {
      return false;
    }
    const style = window.getComputedStyle(el);
    return style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0;
  }

  function controls(form) {
    return Array.from(form.querySelectorAll('input, textarea, select'))
      .filter(isInspectable);
  }

  const form = forms
    .map((item) => ({ item, count: controls(item).length }))
    .sort((a, b) => b.count - a.count)[0]?.item;
  if (!form) return null;

  function labelFor(el) {
    if (el.id) {
      const explicit = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (explicit?.innerText?.trim()) return explicit.innerText.trim();
    }
    const wrapping = el.closest('label');
    if (wrapping?.innerText?.trim()) return wrapping.innerText.trim();
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const text = labelledBy.split(/\s+/).map((id) => document.getElementById(id)?.innerText || '').join(' ').trim();
      if (text) return text;
    }
    return el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.name || el.id || '';
  }

  const result = [];
  const seenRadios = new Set();
  const seenCheckboxGroups = new Set();
  for (const el of controls(form)) {
    const type = (el.type || el.tagName).toLowerCase();
    if (type === 'radio' && el.name) {
      if (seenRadios.has(el.name)) continue;
      seenRadios.add(el.name);
      const group = controls(form).filter((candidate) => candidate.type === 'radio' && candidate.name === el.name);
      const marker = `jobs-agent-${result.length}`;
      group.forEach((candidate) => candidate.setAttribute('data-jobs-agent-field', marker));
      const legend = el.closest('fieldset')?.querySelector('legend')?.innerText?.trim();
      result.push({
        marker,
        label: legend || labelFor(el),
        name: el.name,
        type: 'radio',
        required: group.some((candidate) => candidate.required || candidate.getAttribute('aria-required') === 'true'),
        options: group.map((candidate) => labelFor(candidate) || candidate.value),
      });
      continue;
    }
    if (type === 'checkbox' && el.name) {
      const group = controls(form).filter((candidate) => candidate.type === 'checkbox' && candidate.name === el.name);
      if (group.length > 1) {
        if (seenCheckboxGroups.has(el.name)) continue;
        seenCheckboxGroups.add(el.name);
        const marker = `jobs-agent-${result.length}`;
        group.forEach((candidate) => candidate.setAttribute('data-jobs-agent-field', marker));
        const legend = el.closest('fieldset')?.querySelector('legend')?.innerText?.trim();
        const description = el.getAttribute('description')?.trim();
        result.push({
          marker,
          label: description || legend || labelFor(el),
          name: el.name,
          type: 'multi-select',
          required: group.some((candidate) => candidate.required || candidate.getAttribute('aria-required') === 'true'),
          options: group.map((candidate) => labelFor(candidate) || candidate.value),
        });
        continue;
      }
    }

    const marker = `jobs-agent-${result.length}`;
    el.setAttribute('data-jobs-agent-field', marker);
    result.push({
      marker,
      label: labelFor(el),
      name: el.name || el.id || marker,
      type: el.getAttribute('role') === 'combobox' ? 'combobox' : type,
      required: Boolean(el.required || el.getAttribute('aria-required') === 'true'),
      options: el.tagName === 'SELECT'
        ? Array.from(el.options).filter((option) => option.value || option.text).map((option) => option.text.trim() || option.value)
        : [],
    });
  }

  const submitCandidates = Array.from(form.querySelectorAll('button[type="submit"], input[type="submit"], button:not([type])'))
    .filter((el) => !el.disabled);
  let submit = null;
  if (submitCandidates.length === 1) {
    const label = (submitCandidates[0].innerText || submitCandidates[0].value || '').trim();
    const lowered = label.toLowerCase();
    const looksFinal = /\b(submit|apply)\b/.test(lowered)
      && !/\b(next|continue|review|save|preview)\b/.test(lowered);
    if (looksFinal) {
      submitCandidates[0].setAttribute('data-jobs-agent-submit', 'final');
      submit = {
        selector: '[data-jobs-agent-submit="final"]',
        label,
      };
    }
  }

  return {
    action: form.action || window.location.href,
    fields: result,
    submit,
  };
}
"""


def _kind(raw_type: str) -> FieldKind:
    value = raw_type.casefold()
    mapping = {
        "textarea": FieldKind.TEXTAREA,
        "email": FieldKind.EMAIL,
        "tel": FieldKind.TEL,
        "url": FieldKind.URL,
        "date": FieldKind.DATE,
        "month": FieldKind.DATE,
        "number": FieldKind.NUMBER,
        "select-one": FieldKind.SELECT,
        "select-multiple": FieldKind.SELECT,
        "combobox": FieldKind.COMBOBOX,
        "multi-select": FieldKind.MULTI_SELECT,
        "checkbox": FieldKind.CHECKBOX,
        "radio": FieldKind.RADIO,
        "file": FieldKind.FILE,
        "text": FieldKind.TEXT,
        "search": FieldKind.TEXT,
    }
    return mapping.get(value, FieldKind.UNKNOWN)


def _fingerprint(
    adapter: str,
    action_url: str,
    fields: tuple[FormField, ...],
    submit_label: str | None,
) -> str:
    payload = {
        "adapter": adapter,
        "action_url": action_url,
        "fields": [field.fingerprint_payload() for field in fields],
        "submit_label": (submit_label or "").strip(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class GenericAdapter(ApplicationAdapter):
    name = "generic"

    def supports(self, url: str, page: Page) -> int:
        return 1 if page.locator("form").count() else 0

    def inspect(self, page: Page) -> ApplicationForm:
        raw: dict[str, Any] | None = page.evaluate(_INSPECT_SCRIPT)
        if not raw:
            raise RuntimeError("no HTML form found on the application page")

        fields = tuple(
            FormField(
                key=canonical_key(item["label"], item["name"], item["type"]),
                label=item["label"],
                name=item["name"],
                kind=_kind(item["type"]),
                selector=f'[data-jobs-agent-field="{item["marker"]}"]',
                required=bool(item["required"]),
                options=tuple(item.get("options") or ()),
                sensitive=canonical_key(item["label"], item["name"], item["type"])
                in SENSITIVE_KEYS,
            )
            for item in raw["fields"]
        )
        action_url = raw["action"]
        submit_label = (raw.get("submit") or {}).get("label")
        return ApplicationForm(
            adapter=self.name,
            source_url=page.url,
            action_url=action_url,
            fields=fields,
            submit_selector=(raw.get("submit") or {}).get("selector"),
            submit_label=submit_label,
            fingerprint=_fingerprint(self.name, action_url, fields, submit_label),
        )

    @staticmethod
    def _choose_radio(locator, value: Any) -> bool:
        wanted = str(value).strip().casefold()
        for index in range(locator.count()):
            option = locator.nth(index)
            label = option.evaluate(
                """el => {
                    if (el.id) {
                      const explicit = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                      if (explicit) return explicit.innerText;
                    }
                    return el.closest('label')?.innerText || el.value || '';
                }"""
            )
            raw_value = option.get_attribute("value") or ""
            if wanted in {label.strip().casefold(), raw_value.strip().casefold()}:
                option.check()
                return True
        return False

    @staticmethod
    def _choose_checkbox_group(locator, value: Any) -> bool:
        raw_values = value if isinstance(value, (list, tuple, set)) else (value,)
        wanted = {str(item).strip().casefold() for item in raw_values if str(item).strip()}
        matched: set[str] = set()
        for index in range(locator.count()):
            option = locator.nth(index)
            label = option.evaluate(
                """el => {
                    if (el.id) {
                      const explicit = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                      if (explicit) return explicit.innerText;
                    }
                    return el.closest('label')?.innerText || el.value || '';
                }"""
            )
            candidates = {
                label.strip().casefold(),
                (option.get_attribute("value") or "").strip().casefold(),
            }
            selected = wanted.intersection(candidates)
            if selected:
                option.check()
                matched.update(selected)
        return bool(wanted) and matched == wanted

    @staticmethod
    def _choose_combobox(page: Page, locator, value: Any) -> bool:
        wanted = str(value).strip()
        if not wanted or locator.count() != 1:
            return False
        locator.click()
        locator.fill(wanted)
        page.wait_for_timeout(100)
        options = page.get_by_role("option")
        for index in range(options.count()):
            option = options.nth(index)
            if option.is_visible() and option.inner_text().strip().casefold() == wanted.casefold():
                option.click()
                return True
        locator.press("Escape")
        return False

    def fill(self, page: Page, form: ApplicationForm, answers: ResolvedAnswers) -> FillReport:
        filled: list[str] = []
        filled_selectors: set[str] = set()
        skipped: list[str] = []
        validation_errors: list[str] = []

        for field in form.fields:
            if field.key not in answers.values:
                if field.required:
                    skipped.append(field.key)
                continue
            value = answers.values[field.key]
            locator = page.locator(field.selector)
            try:
                if field.kind is FieldKind.FILE:
                    locator.set_input_files(str(value))
                elif field.kind is FieldKind.SELECT:
                    try:
                        locator.select_option(label=str(value))
                    except Exception:
                        locator.select_option(value=str(value))
                elif field.kind is FieldKind.COMBOBOX:
                    if not self._choose_combobox(page, locator, value):
                        skipped.append(field.key)
                        continue
                elif field.kind is FieldKind.MULTI_SELECT:
                    if not self._choose_checkbox_group(locator, value):
                        skipped.append(field.key)
                        continue
                elif field.kind is FieldKind.CHECKBOX:
                    if isinstance(value, bool):
                        checked = value
                    elif str(value).strip().casefold() in {"true", "yes", "1"}:
                        checked = True
                    elif str(value).strip().casefold() in {"false", "no", "0"}:
                        checked = False
                    else:
                        raise ValueError("checkbox answer is not an explicit boolean")
                    locator.set_checked(checked)
                elif field.kind is FieldKind.RADIO:
                    if not self._choose_radio(locator, value):
                        skipped.append(field.key)
                        continue
                elif field.kind is FieldKind.UNKNOWN:
                    skipped.append(field.key)
                    continue
                else:
                    locator.fill(str(value))
                filled.append(field.key)
                filled_selectors.add(field.selector)
            except Exception as exc:
                validation_errors.append(f"{field.key}: {type(exc).__name__}")

        # HTML validity is useful but never taken as proof that submission is safe.
        for field in form.fields:
            if field.required:
                try:
                    locator = page.locator(field.selector)
                    if field.kind is FieldKind.MULTI_SELECT:
                        valid = any(locator.nth(index).is_checked() for index in range(locator.count()))
                    elif field.kind is FieldKind.COMBOBOX:
                        valid = field.selector in filled_selectors
                    else:
                        valid = locator.first.evaluate(
                            "el => el.checkValidity ? el.checkValidity() : true"
                        )
                except Exception:
                    valid = False
                if not valid:
                    validation_errors.append(f"{field.key}: browser validation failed")

        return FillReport(
            form_fingerprint=form.fingerprint,
            filled=tuple(dict.fromkeys(filled)),
            skipped=tuple(dict.fromkeys(skipped)),
            validation_errors=tuple(dict.fromkeys(validation_errors)),
        )

    def read_receipt(self, page: Page) -> SubmissionReceipt | None:
        confirmation = page.locator(
            '[data-application-confirmation], [data-testid="application-confirmation"]'
        )
        if confirmation.count() == 1 and confirmation.is_visible():
            message = confirmation.inner_text().strip()
            confirmation_id = confirmation.get_attribute("data-confirmation-id")
            if not confirmation_id:
                match = re.search(r"\b(?:confirmation|application)[ #:]*([A-Z0-9-]{4,})\b", message, re.I)
                confirmation_id = match.group(1) if match else None
            return SubmissionReceipt(confirmation_id, page.url, message or None)
        return None
