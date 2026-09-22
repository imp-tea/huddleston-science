"""Build and preview only the deployable directory on localhost."""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from build import build, OUT

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(OUT), **kwargs)
    def list_directory(self, path):
        self.send_error(404)
        return None

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8766)
    args=parser.parse_args()
    build()
    print(f'Open http://127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
