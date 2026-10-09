import html
import json
import re
import urllib.parse
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