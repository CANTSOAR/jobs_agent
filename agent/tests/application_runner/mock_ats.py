from __future__ import annotations

import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


class MockAtsState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.post_paths: list[str] = []

    def record_post(self, path: str) -> None:
        with self.lock:
            self.post_paths.append(path)

    def count(self, path: str) -> int:
        with self.lock:
            return self.post_paths.count(path)


def _application_html(query: dict[str, list[str]]) -> bytes:
    unknown = "unknown" in query
    changed = "changed" in query
    sensitive = "sensitive" in query
    captcha = "captcha" in query
    dynamic = "dynamic" in query
    load_post = "loadpost" in query
    multi_select = "multi" in query
    combobox = "combo" in query
    extra = (
        '<label for="favorite-protocol">Favorite protocol</label>'
        '<input id="favorite-protocol" name="favorite_protocol" required>'
        if unknown
        else ""
    )
    changed_option = '<option value="CA">Canada</option>' if changed else ""
    sensitive_question = (
        """
        <fieldset>
          <legend>Will you now or in the future require sponsorship?</legend>
          <label><input type="radio" name="requires_sponsorship" value="Yes" required>Yes</label>
          <label><input type="radio" name="requires_sponsorship" value="No" required>No</label>
        </fieldset>
        """
        if sensitive
        else ""
    )
    multi_select_question = (
        """
        <fieldset>
          <legend>Undergrad Discipline(s)</legend>
          <label><input description="Undergrad Discipline(s)" type="checkbox" name="disciplines[]" value="Mathematics" required>Mathematics</label>
          <label><input description="Undergrad Discipline(s)" type="checkbox" name="disciplines[]" value="Computer Science" required>Computer Science</label>
        </fieldset>
        """
        if multi_select
        else ""
    )
    country_control = (
        """
        <label id="country-label" for="country">Country</label>
        <input id="country" name="country" role="combobox" aria-labelledby="country-label"
               aria-controls="country-options" aria-expanded="false" aria-required="true" required>
        <div id="country-options" role="listbox" hidden>
          <div role="option" data-value="US">United States</div>
          <div role="option" data-value="CA">Canada</div>
        </div>
        """
        if combobox
        else f"""
        <label for="country">Country</label>
        <select id="country" name="country" required>
          <option value="">Choose one</option>
          <option value="US">United States</option>
          {changed_option}
        </select>
        """
    )
    combobox_script = (
        """
        const combo = document.querySelector('#country');
        const comboOptions = document.querySelector('#country-options');
        combo.addEventListener('input', () => {
          comboOptions.hidden = false;
          combo.setAttribute('aria-expanded', 'true');
        });
        for (const option of comboOptions.querySelectorAll('[role="option"]')) {
          option.addEventListener('click', () => {
            combo.value = option.textContent.trim();
            combo.dataset.selectedValue = option.dataset.value;
            comboOptions.hidden = true;
            combo.setAttribute('aria-expanded', 'false');
            combo.dispatchEvent(new Event('change', { bubbles: true }));
          });
        }
        """
        if combobox
        else ""
    )
    captcha_widget = '<div class="captcha-widget" data-sitekey="test">Challenge</div>' if captcha else ""
    dynamic_script = """
    const country = document.querySelector('#country');
    country.addEventListener('change', () => {
      if (document.querySelector('[data-dynamic-question]')) return;
      const fieldset = document.createElement('fieldset');
      fieldset.setAttribute('data-dynamic-question', 'true');
      fieldset.innerHTML = `
        <legend>Are you legally authorized to work in Canada?</legend>
        <label><input type="radio" name="work_authorization" value="Yes" required>Yes</label>
        <label><input type="radio" name="work_authorization" value="No" required>No</label>
      `;
      document.querySelector('form').insertBefore(fieldset, document.querySelector('button'));
    });
    """ if dynamic else ""
    load_post_script = "fetch('/page-load-write', {method: 'POST', body: 'loaded=1'});" if load_post else ""
    return f"""<!doctype html>
<html><body>
  <main data-mock-ats>
    <h1>Software Engineering Intern</h1>
    <form action="/submit" method="post" enctype="multipart/form-data">
      <label for="first-name">First name</label>
      <input id="first-name" name="first_name" required>
      <label for="last-name">Last name</label>
      <input id="last-name" name="last_name" required>
      <label for="email">Email address</label>
      <input id="email" name="email" type="email" required>
      {country_control}
      <fieldset>
        <legend>Preferred work setting</legend>
        <label><input type="radio" name="work_setting" value="Remote" required>Remote</label>
        <label><input type="radio" name="work_setting" value="Onsite" required>Onsite</label>
      </fieldset>
      {sensitive_question}
      {multi_select_question}
      {captcha_widget}
      <label for="resume">Resume</label>
      <input id="resume" name="resume" type="file" required>
      {extra}
      <button type="submit">Submit application</button>
    </form>
  </main>
  <script>
    for (const input of document.querySelectorAll('input,select,textarea')) {{
      input.addEventListener('input', () => fetch('/autosave', {{method: 'POST', body: 'draft=1'}}));
      input.addEventListener('change', () => fetch('/autosave', {{method: 'POST', body: 'draft=1'}}));
    }}
    {dynamic_script}
    {combobox_script}
    {load_post_script}
  </script>
</body></html>""".encode()


class _Handler(BaseHTTPRequestHandler):
    server: "MockAtsServer"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
        parsed = urlsplit(self.path)
        if parsed.path == "/apply":
            body = _application_html(parse_qs(parsed.query, keep_blank_values=True))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/success":
            body = b"""<!doctype html><html><body>
              <div data-application-confirmation data-confirmation-id="MOCK-1234">
                Application confirmation MOCK-1234
              </div>
            </body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
        parsed = urlsplit(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        self.server.state.record_post(parsed.path)
        if parsed.path == "/submit":
            self.send_response(303)
            self.send_header("Location", "/success")
            self.end_headers()
            return
        if parsed.path == "/autosave":
            self.send_response(204)
            self.end_headers()
            return
        self.send_error(404)

    def log_message(self, format: str, *args) -> None:
        return


class MockAtsServer(ThreadingHTTPServer):
    def __init__(self, address, handler, state: MockAtsState):
        super().__init__(address, handler)
        self.state = state


@contextmanager
def serve_mock_ats():
    state = MockAtsState()
    server = MockAtsServer(("127.0.0.1", 0), _Handler, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
