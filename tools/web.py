import html
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
        query = self._parse_input(input_data)

        if not query:
            return "Web search error: Search query is empty."

        encoded = urllib.parse.urlencode({
            "q": query
        })

        url = (
            "https://html.duckduckgo.com/html/"
            f"?{encoded}"
        )

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent
            }
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=15
            ) as response:
                raw = response.read().decode(
                    "utf-8",
                    errors="replace"
                )

        except Exception as e:
            return (
                "Web search error: "
                f"{type(e).__name__}: {e}"
            )

        result_pattern = re.compile(
            r'<div[^>]+class="result[^"]*"[^>]*>'
            r'.*?'
            r'<a[^>]+class="result__a"[^>]+'
            r'href="([^"]+)"[^>]*>'
            r'(.*?)'
            r'</a>'
            r'.*?'
            r'<a[^>]+class="result__snippet"[^>]*>'
            r'(.*?)'
            r'</a>',
            re.IGNORECASE | re.DOTALL
        )

        matches = result_pattern.findall(raw)

        if not matches:
            # Fallback 1: simpler pattern for result links
            fallback_pattern = re.compile(
                r'<a[^>]+class="result__a"[^>]+'
                r'href="([^"]+)"[^>]*>'
                r'(.*?)'
                r'</a>',
                re.IGNORECASE | re.DOTALL
            )

            matches = [
                (link, title, "")
                for link, title
                in fallback_pattern.findall(raw)
            ]

        if not matches:
            # Fallback 2: generic pattern for any links with result-like classes
            generic_pattern = re.compile(
                r'<a[^>]+class="[^"]*result[^"]*"[^>]+'
                r'href="([^"]+)"[^>]*>'
                r'(.*?)'
                r'</a>',
                re.IGNORECASE | re.DOTALL
            )

            matches = [
                (link, title, "")
                for link, title
                in generic_pattern.findall(raw)
            ]

        if not matches:
            # Fallback 3: try to find any external links in the page
            any_link_pattern = re.compile(
                r'<a[^>]+href="(https?://[^"]+)"[^>]*>'
                r'(.*?)'
                r'</a>',
                re.IGNORECASE | re.DOTALL
            )

            matches = [
                (link, title, "")
                for link, title
                in any_link_pattern.findall(raw)
                if "duckduckgo" not in link.lower()
            ]

        if not matches:
            return (
                "Web search error: "
                "No web search results found."
            )

        results = []
        base_url = "https://html.duckduckgo.com"

        for index, (link, title, snippet) in enumerate(
            matches[:6],
            start=1
        ):
            title = re.sub(
                r"<.*?>",
                "",
                title
            )

            snippet = re.sub(
                r"<.*?>",
                "",
                snippet
            )

            title = html.unescape(
                title
            ).strip()

            snippet = html.unescape(
                snippet
            ).strip()

            link = html.unescape(
                link
            ).strip()

            # Handle relative URLs by converting to absolute
            if link.startswith("//"):
                link = "https:" + link
            elif link.startswith("/"):
                link = base_url + link
            elif not link.startswith(("http://", "https://")):
                link = base_url + "/" + link

            results.append(
                f"[{index}]\n"
                f"Title: {title}\n"
                f"URL: {link}\n"
                f"Snippet: {snippet}"
            )

        return "\n\n".join(results)


    def _validate_public_url(self, url):
        """Reject local/private destinations before making outbound requests."""
        parsed = urllib.parse.urlsplit(str(url).strip())
        if parsed.scheme.lower() not in {"http", "https"}:
            raise ValueError("Only http:// and https:// URLs are supported.")
        if not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("URL must have a hostname and cannot contain credentials.")
        if parsed.port not in (None, 80, 443):
            raise ValueError("Only standard HTTP/HTTPS ports are allowed.")

        hostname = parsed.hostname.rstrip(".").lower()
        if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
            raise ValueError("Local hostnames are not allowed.")

        try:
            addresses = [ipaddress.ip_address(hostname)]
        except ValueError:
            try:
                records = socket.getaddrinfo(
                    hostname,
                    parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
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
        return str(url).strip()

    def fetch(self, input_data):
        """Fetch a public web page as bounded plain text, following safe redirects only."""
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

        try:
            url = self._validate_public_url(url)
        except (ValueError, TypeError) as exc:
            return f"WEB_FETCH_ERROR: {exc}"

        validator = self._validate_public_url

        class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                absolute = urllib.parse.urljoin(req.full_url, newurl)
                validator(absolute)
                return super().redirect_request(req, fp, code, msg, headers, absolute)

        request = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent, "Accept": "text/html,text/plain,application/json,application/xml"},
        )
        opener = urllib.request.build_opener(SafeRedirectHandler)
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
            document = re.sub(r"(?is)<(script|style|noscript|svg)\\b[^>]*>.*?</\\1\\s*>", " ", document)
            document = re.sub(r"(?s)<[^>]+>", " ", document)
            document = html.unescape(document)
        document = re.sub(r"[ \\t\\r\\f\\v]+", " ", document)
        document = re.sub(r"\\n\\s*\\n+", "\\n\\n", document).strip()
        if not document:
            return "WEB_FETCH_ERROR: The page returned no readable text."

        return (
            "WEB_FETCH_SUCCESS\\n"
            f"URL: {final_url}\\n"
            f"Content-Type: {content_type or 'unknown'}\\n"
            f"Characters: {len(document)}\\n"
            "BEGIN_PAGE_TEXT\\n"
            f"{document[:12000]}\\n"
            "END_PAGE_TEXT"
        )
