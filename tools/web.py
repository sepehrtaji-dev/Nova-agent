import html
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

    def run(self, query):

        query = str(query).strip()

        if not query:
            return "Search query is empty."

        encoded = urllib.parse.urlencode(
            {"q": query}
        )

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
                    errors="ignore"
                )

        except Exception as e:

            return (
                "Web search failed: "
                f"{e}"
            )

        pattern = re.compile(
            r'<a[^>]+class="result__a"[^>]+'
            r'href="([^"]+)"[^>]*>'
            r'(.*?)</a>',
            re.IGNORECASE |
            re.DOTALL
        )

        matches = pattern.findall(raw)

        if not matches:
            return "No web search results found."

        results = []

        for index, (link, title) in enumerate(
            matches[:6],
            start=1
        ):

            title = re.sub(
                r"<.*?>",
                "",
                title
            )

            title = html.unescape(
                title
            ).strip()

            link = html.unescape(
                link
            ).strip()

            if link.startswith("//"):
                link = "https:" + link

            results.append(
                f"[{index}]\n"
                f"Title: {title}\n"
                f"URL: {link}"
            )

        return "\n\n".join(results)