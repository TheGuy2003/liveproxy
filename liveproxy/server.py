import os
import shlex
from http.server import BaseHTTPRequestHandler, HTTPServer
from shutil import which
from socketserver import ThreadingMixIn
from time import time
from urllib.parse import unquote
from functools import lru_cache

ACCEPTABLE_ERRNO = (
    errno.ECONNABORTED,
    errno.ECONNRESET,
    errno.EINVAL,
    errno.EPIPE,
)
if os.name == 'nt':
    ACCEPTABLE_ERRNO += (errno.WSAECONNABORTED,)

_re_streamlink = re.compile(r"streamlink", re.IGNORECASE)
_re_youtube_dl = re.compile(r"(?:youtube|yt)[_-]dl(?:p)?", re.IGNORECASE)

log = logging.getLogger(__name__.replace("liveproxy.", ""))

@lru_cache()
def find_executable(name):
    return which(name, mode=os.F_OK | os.X_OK)

class HTTPRequest(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _headers(self, status, content, connection=False):
        self.send_response(status)
        self.send_header("Server", "LiveProxy")
        self.send_header("Content-type", content)
        if connection:
            self.send_header("Connection", connection)
        self.end_headers()

    def do_HEAD(self):
        """Respond to a HEAD request."""
        self._headers(404, "text/html", connection="close")

    def do_GET(self):
        """Respond to a GET request."""
        random_id = hex(int(time()))[5:]
        log = logging.getLogger("{name}.{random_id}".format(
            name=__name__.replace("liveproxy.", ""),
            random_id=random_id,
        ))

        log.info(f"User-Agent: {self.headers.get('User-Agent', '???')}")
        log.info(f"Client: {self.client_address}")
        log.info(f"Address: {self.address_string()}")

        if self.path.startswith("/base64/"):
            try:
                arglist = shlex.split(base64.urlsafe_b64decode(self.path.split("/")[2]).decode("UTF-8"))
            except base64.binascii.Error as err:
                log.error(f"invalid base64 URL: {err}")
                self._headers(404, "text/html", connection="close")
                return
        elif self.path.startswith("/cmd/"):
            self.path = self.path[5:]
            if self.path.endswith("/"):
                self.path = self.path[:-1]
            arglist = shlex.split(unquote(self.path))
        else:
            self._headers(404, "text/html", connection="close")
            return

        prog = find_executable(arglist[0])
        if not prog:
            log.error(f"invalid prog, can not find '{arglist[0]}' on your system")
            return

        log.debug(f"Video-Software: {prog}")
        if _re_streamlink.search(prog):
            arglist.extend(["--stdout", "--loglevel", "none"])
        elif _re_youtube_dl.search(prog):
            arglist.extend(["-o", "-"])
        else:
            self._headers(404, "text/html", connection="close")
            return

        log.debug(f"arglist: {arglist}")
        try:
            output = subprocess.run(arglist, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except Exception as ex:
            log.error(f"Failed to run {prog} {arglist} {ex}")
            self._headers(404, "text/html", connection="close")
            return

        self._headers(200, "application/octet-stream")
        self.wfile.write(output.stdout)

class ThreadingServer(ThreadingMixIn, HTTPServer):
    pass

def main(port=0):
    server = ThreadingServer(("", port), HTTPRequest)
    log.info(f"Listening on {server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down...")
        server.shutdown()
        server.server_close()

if __name__ == "__main__":
    main()
