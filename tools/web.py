import base64
import html
import http.client
import ssl
import ipaddress
import socket
import json
import re
import urllib.parse
import urllib.error
import urllib.request


class WebSearchTool:
    def __init__(self):
        self.user_agent = (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "Chrome/145.0 Safari/537.36"
        )

    def _parse_input(self, input_data):
        if isinstance(input_data, dict):
            return input_data.get("query", "")

        if not isinstance(input_data, str):
            return ""

        text = input_data.strip()

        if not text:
            return ""

        try:
            data = json.loads(text)

            if isinstance(data, dict):
                query = (
                    data.get("query")
                    or data.get("search")
                    or data.get("q")
                    or data.get("text")
                    or ""
                )

                if isinstance(query, str):
                    return query.strip()

                return ""

        except json.JSONDecodeError:
            pass

        return text

    def run(self, input_data):
        """Search the public web and return bounded, source-linked results.

        Accepts a string or a dict containing query/search/q. The output keeps
        Nova's existing numbered Title/URL/Snippet contract for its planner and
        verifier. No search results are fabricated when a provider fails.
        """
        from html.parser import HTMLParser

        query = self._parse_input(input_data)
        if not query:
            return "Web search error: Search query is empty."
        query = " ".join(query.split())[:500]

        class SearchResultParser(HTMLParser):
            def __init__(self, provider):
                super().__init__(convert_charrefs=True)
                self.provider = provider
                self.results = []
                self._current = None
                self._capture = None
                self._buffer = []
                self._in_result = False
                self._result_depth = 0

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                classes = set((attrs.get("class") or "").split())
                if self.provider == "ddg":
                    if tag == "div" and "result" in classes and "result--ad" not in classes:
                        self._in_result = True
                        self._result_depth = 1
                        self._current = {"title": "", "url": "", "snippet": ""}
                    elif self._in_result and tag == "div" and (
                        "result__snippet" in classes or "result__body" in classes
                    ):
                        self._result_depth += 1
                        self._capture = "snippet"
                        self._buffer = []
                    elif self._in_result and tag == "div":
                        self._result_depth += 1
                    elif self._in_result and tag == "a" and "result__a" in classes:
                        self._current["url"] = attrs.get("href", "")
                        self._capture = "title"
                        self._buffer = []
                    elif self._in_result and tag == "a" and "result__snippet" in classes:
                        self._capture = "snippet"
                        self._buffer = []
                else:
                    if tag == "li" and "b_algo" in classes:
                        self._in_result = True
                        self._result_depth = 1
                        self._current = {"title": "", "url": "", "snippet": ""}
                    elif self._in_result and tag == "li":
                        self._result_depth += 1
                    elif self._in_result and tag == "a" and not self._current.get("url"):
                        href = attrs.get("href", "")
                        if href.startswith(("https://", "http://")):
                            self._current["url"] = href
                            self._capture = "title"
                            self._buffer = []
                    elif self._in_result and tag in {"p", "div"} and (
                        tag == "p" or "b_caption" in classes
                    ):
                        self._capture = "snippet"
                        self._buffer = []

            def handle_data(self, data):
                if self._capture:
                    self._buffer.append(data)

            def handle_endtag(self, tag):
                if self._capture and (
                    (self._capture == "title" and tag == "a")
                    or (self._capture == "snippet" and tag in {"a", "div", "p"})
                ):
                    value = " ".join(" ".join(self._buffer).split())
                    if self._current is not None and value:
                        if not self._current.get(self._capture):
                            self._current[self._capture] = value
                    self._capture = None
                    self._buffer = []
                closes_result = (
                    self.provider == "ddg" and tag == "div"
                ) or (
                    self.provider == "bing" and tag == "li"
                )
                if self._in_result and closes_result:
                    self._result_depth -= 1
                    if self._result_depth <= 0:
                        if self._current and self._current.get("url") and self._current.get("title"):
                            self.results.append(self._current)
                        self._current = None
                        self._in_result = False
                        self._result_depth = 0
                        self._capture = None
                        self._buffer = []

        providers = (
            (
                "ddg",
                "https://html.duckduckgo.com/html/",
                {"q": query},
            ),
            (
                "bing",
                "https://www.bing.com/search",
                {"q": query, "count": "10"},
            ),
        )
        errors = []
        for provider, endpoint, params in providers:
            url = endpoint + "?" + urllib.parse.urlencode(params)
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.8",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=12) as response:
                    if response.status != 200:
                        errors.append(f"{provider}: HTTP {response.status}")
                        continue
                    raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    errors.append(f"{provider}: response exceeded 2 MB")
                    continue
                parser = SearchResultParser(provider)
                parser.feed(raw.decode("utf-8", errors="replace"))
                parser.close()
                cleaned = []
                seen = set()
                for item in parser.results:
                    result_url = html.unescape(item.get("url", "")).strip()
                    if provider == "bing":
                        bparsed = urllib.parse.urlsplit(result_url)
                        if (bparsed.hostname or "").endswith("bing.com") and bparsed.path.startswith("/ck/a"):
                            token = urllib.parse.parse_qs(bparsed.query).get("u", [""])[0]
                            if token.startswith("a1"):
                                try:
                                    body = token[2:]
                                    body += "=" * (-len(body) % 4)
                                    result_url = base64.urlsafe_b64decode(body).decode("utf-8", "replace")
                                except Exception:
                                    pass
                    if provider == "ddg":
                        parsed_link = urllib.parse.urlsplit(result_url)
                        if parsed_link.hostname and parsed_link.hostname.endswith("duckduckgo.com"):
                            target = urllib.parse.parse_qs(parsed_link.query).get("uddg", [""])[0]
                            if target:
                                result_url = urllib.parse.unquote(target)
                    parsed = urllib.parse.urlsplit(result_url)
                    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                        continue
                    if parsed.username or parsed.password:
                        continue
                    host = parsed.hostname.lower().rstrip(".")
                    if host in {"duckduckgo.com", "www.duckduckgo.com", "bing.com", "www.bing.com"}:
                        continue
                    normalized = urllib.parse.urlunsplit(
                        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, "")
                    )
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    title = " ".join(html.unescape(item.get("title", "")).split())
                    snippet = " ".join(html.unescape(item.get("snippet", "")).split())
                    if not title:
                        continue
                    cleaned.append((title[:300], normalized[:2000], snippet[:1000]))
                    if len(cleaned) >= 8:
                        break
                if cleaned:
                    return "\\n\\n".join(
                        f"[{index}]\\nTitle: {title}\\nURL: {result_url}\\nSnippet: {snippet or '(No snippet provided by the search engine.)'}"
                        for index, (title, result_url, snippet) in enumerate(cleaned, start=1)
                    )
                errors.append(f"{provider}: no parseable results")
            except Exception as exc:
                errors.append(f"{provider}: {type(exc).__name__}: {exc}")

        details = "; ".join(errors)[:1200]
        return (
            "Web search error: Search providers returned no usable results. "
            "No results were invented."
            + (f" Details: {details}" if details else "")
        )

    def _resolve_public_url(self, url):
        """Validate a URL and return its resolved public IPs for connection pinning."""
        parsed = urllib.parse.urlsplit(str(url).strip())
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise ValueError("Only http:// and https:// URLs are supported.")
        if not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("URL must have a hostname and cannot contain credentials.")
        if parsed.port not in (None, 80, 443):
            raise ValueError("Only standard HTTP/HTTPS ports are allowed.")

        hostname = parsed.hostname.rstrip(".").lower()
        if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
            raise ValueError("Local hostnames are not allowed.")

        try:
            addresses = [ipaddress.ip_address(hostname)]
        except ValueError:
            try:
                records = socket.getaddrinfo(
                    hostname,
                    parsed.port or (443 if scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
            except OSError as exc:
                raise ValueError(f"Could not resolve public hostname: {hostname}") from exc
            addresses = []
            for record in records:
                try:
                    addresses.append(ipaddress.ip_address(record[4][0]))
                except ValueError:
                    continue

        if not addresses:
            raise ValueError("Hostname did not resolve to an IP address.")
        if any(not address.is_global for address in addresses):
            raise ValueError("Private, loopback, reserved, or non-public IP destinations are blocked.")
        return str(url).strip(), hostname, [str(address) for address in addresses]

    def _validate_public_url(self, url):
        """Reject local/private destinations before making outbound requests."""
        return self._resolve_public_url(url)[0]

    def fetch(self, input_data):
        """Input object: {"url": "https://public.example/path"}. Fetches bounded readable text from a public HTTP/HTTPS page; private/local destinations are rejected."""
        if isinstance(input_data, dict):
            url = input_data.get("url", "")
        elif isinstance(input_data, str):
            raw = input_data.strip()
            try:
                payload = json.loads(raw)
                url = payload.get("url", "") if isinstance(payload, dict) else raw
            except json.JSONDecodeError:
                url = raw
        else:
            url = ""

        if not isinstance(url, str) or not url.strip():
            return "WEB_FETCH_ERROR: A URL is required."

        pinned_addresses = {}

        def pin_url(candidate):
            clean_url, hostname, addresses = self._resolve_public_url(candidate)
            # Use a resolved address for the actual socket, rather than allowing
            # urllib/libcurl to resolve the hostname a second time (DNS rebinding).
            pinned_addresses[hostname] = addresses[0]
            return clean_url

        try:
            url = pin_url(url)
        except (ValueError, TypeError) as exc:
            return f"WEB_FETCH_ERROR: {exc}"

        class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                absolute = urllib.parse.urljoin(req.full_url, newurl)
                pin_url(absolute)
                return super().redirect_request(req, fp, code, msg, headers, absolute)

        class PinnedHTTPConnection(http.client.HTTPConnection):
            def __init__(self, host, *args, pinned_ip=None, **kwargs):
                self._pinned_ip = pinned_ip
                super().__init__(host, *args, **kwargs)

            def connect(self):
                if not self._pinned_ip:
                    raise OSError("No validated IP address is pinned for this host.")
                self.sock = socket.create_connection(
                    (self._pinned_ip, self.port), self.timeout, self.source_address
                )
                if self._tunnel_host:
                    self._tunnel()

        class PinnedHTTPSConnection(http.client.HTTPSConnection):
            def __init__(self, host, *args, pinned_ip=None, context=None,
                         check_hostname=None, **kwargs):
                self._pinned_ip = pinned_ip
                self._context = context or ssl.create_default_context()
                if check_hostname is not None:
                    self._context.check_hostname = check_hostname
                super().__init__(host, *args, context=self._context, **kwargs)

            def connect(self):
                if not self._pinned_ip:
                    raise OSError("No validated IP address is pinned for this host.")
                self.sock = socket.create_connection(
                    (self._pinned_ip, self.port), self.timeout, self.source_address
                )
                if self._tunnel_host:
                    self._tunnel()
                self.sock = self._context.wrap_socket(
                    self.sock, server_hostname=self.host
                )

        class PinnedHTTPHandler(urllib.request.HTTPHandler):
            def http_open(self, req):
                hostname = (urllib.parse.urlsplit(req.full_url).hostname or "").lower().rstrip(".")
                pinned_ip = pinned_addresses.get(hostname)
                return self.do_open(
                    lambda host, **kwargs: PinnedHTTPConnection(
                        host, pinned_ip=pinned_ip, **kwargs
                    ),
                    req,
                )

        class PinnedHTTPSHandler(urllib.request.HTTPSHandler):
            def https_open(self, req):
                hostname = (urllib.parse.urlsplit(req.full_url).hostname or "").lower().rstrip(".")
                pinned_ip = pinned_addresses.get(hostname)
                return self.do_open(
                    lambda host, **kwargs: PinnedHTTPSConnection(
                        host, pinned_ip=pinned_ip, **kwargs
                    ),
                    req,
                    context=self._context,
                    check_hostname=self._check_hostname,
                )

        request = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent, "Accept": "text/html,text/plain,application/json,application/xml"},
        )
        # Ignore ambient proxy settings: proxying would bypass the pinned socket.
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            SafeRedirectHandler,
            PinnedHTTPHandler,
            PinnedHTTPSHandler,
        )
        try:
            with opener.open(request, timeout=15) as response:
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type and not (
                    content_type.startswith("text/")
                    or content_type in {"application/json", "application/xml", "application/xhtml+xml"}
                ):
                    return f"WEB_FETCH_ERROR: Unsupported content type: {content_type or 'unknown'}"
                raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    return "WEB_FETCH_ERROR: Page exceeds the 1 MB response limit."
                final_url = response.geturl()
                self._validate_public_url(final_url)
        except Exception as exc:
            return f"WEB_FETCH_ERROR: {type(exc).__name__}: {exc}"

        charset = "utf-8"
        try:
            charset = response.headers.get_content_charset() or "utf-8"
        except Exception:
            pass
        document = raw.decode(charset, errors="replace")
        if "html" in content_type:
            document = re.sub(r"(?is)<(script|style|noscript|svg)\b[^>]*>.*?</\1\s*>", " ", document)
            document = re.sub(r"(?s)<[^>]+>", " ", document)
            document = html.unescape(document)
        document = re.sub(r"[ \t\r\f\v]+", " ", document)
        document = re.sub(r"\n\s*\n+", "\n\n", document).strip()
        if not document:
            return "WEB_FETCH_ERROR: The page returned no readable text."

        return (
            "WEB_FETCH_SUCCESS\n"
            f"URL: {final_url}\n"
            f"Content-Type: {content_type or 'unknown'}\n"
            f"Characters: {len(document)}\n"
            "BEGIN_PAGE_TEXT\n"
            f"{document[:12000]}\n"
            "END_PAGE_TEXT"
        )