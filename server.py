#!/usr/bin/env python3

from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
import sys
from os.path import splitext, dirname, realpath, expanduser
import json
from urllib.parse import unquote, urlparse
import time
import traceback

script_path = Path(dirname(realpath(__file__)))

def sound_paths():
    base = 'static/sound/'
    paths = dict()
    for d in (script_path / base).iterdir():
        paths[d.name] = dict(base=base + d.name, files=[])
        for f in d.iterdir():
            paths[d.name]['files'].append(f.name)
    return paths

class TooManyPlayers(Exception):
    pass

class InvalidPlayer(Exception):
    pass

class ShipAlreadyHit(Exception):
    pass

class ShipDead(Exception):
    pass

class OutOfShips(Exception):
    pass

class ShipOverlaps(Exception):
    pass

class AlreadyHit(Exception):
    pass

class PlayersNotReadyYet(Exception):
    pass

class NotYourTurn(Exception):
    pass

class GameAlreadyOver(Exception):
    pass

class OutOfBounds(Exception):
    pass

class Ship(object):

    def __init__(self, coord, size, horizontal):
        self.coord = coord
        self.size = size
        self.horizontal = horizontal
        self.lives = self.size
        self.hits = []

    def _hit(self, x, y):
        h1, h2, c1, c2 = x, y, 0, 1
        if self.horizontal:
            h1, h2, c1, c2 = h2, h1, c2, c1
        ship_hit = h1 == self.coord[c1] and self.coord[c2] <= h2 <= self.size - 1 + self.coord[c2]
        return ship_hit

    def hit(self, x, y):
        ship_hit = self._hit(x, y)
        if ship_hit:
            if (x, y) in self.hits:
                raise ShipAlreadyHit()
            else:
                self.lives -= 1
                self.hits.append((x, y))
            if self.lives == 0:
                raise ShipDead()
        return ship_hit

    def points(self):
        if self.horizontal:
            return [(self.coord[0] + i, self.coord[1]) for i in range(self.size)]
        else:
            return [(self.coord[0], self.coord[1] + i) for i in range(self.size)]

    def allowed(self, other):
        op = other.points()
        forbidden = set()
        for p in op:
            for y in range(p[1] - 1, p[1] + 2):
                for x in range(p[0] - 1, p[0] + 2):
                    forbidden |= {(x, y)}
        for p in self.points():
            if p in forbidden:
                return False
        return True


class BattleshipGame(object):

    def __init__(self, ships={5: 1, 4: 1, 3: 2, 2: 1, 1: 1}):
        self._ships_left = ships
        self.players = []

    def add_player(self):
        token = time.time()
        if len(self.players) < 2:
            self.players.append(dict(
                winner=False,
                ships=[],
                ships_left=dict(self._ships_left),
                hits=[],
                token=token))
            return token
        else:
            raise TooManyPlayers('Too many players')

    def get_squares(self, player, own):
        output = []
        #rows
        for y in range(10):
            row = []
            #squares
            for x in range(10):
                sq = {'txt': '?', 'cls': ['square']}
                if (x, y) in player['hits']:
                    sq['txt'] = 'X'
                    sq['cls'].append('hit')
                for ship in player['ships']:
                    if ship._hit(x, y):
                        if own or (x, y) in player['hits']:
                            sq['txt'] = 'O'
                            sq['cls'].append('ship')
                            if ship.lives == 0:
                                sq['cls'].append('dead')
                            break
                row.append(sq)
            output.append(row)

        return output

    def get_player(self, token, me):
        def test(_token):
            return me == (_token == token)
        return next(p for p in self.players if test(p['token']))

    def add_ship(self, token, coord=None, size=None, horizontal=False):
        player = self.get_player(token, True)
        if (player['ships_left'].get(size) or 0) <= 0:
            raise OutOfShips('No more ships of size {}'.format(size))
        ship = Ship(coord, size, horizontal)
        for p in ship.points():
            for c in p:
                if not 0 <= c <= 9:
                    raise OutOfBounds('Out of bounds {}'.format(p))
        for sh in player['ships']:
            if not sh.allowed(ship):
                raise ShipOverlaps('Can\'t put a ship here')
        player['ships'].append(ship)
        player['ships_left'][size] -= 1

    def winner(self, player):
        if player.get('winner'):
            return True
        else:
            return False

    def hit(self, token, x=None, y=None):
        if not self.ready():
            raise PlayersNotReadyYet('Players aren\'t ready yet')
        for c in x, y:
            if not 0 <= c <= 9:
                raise OutOfBounds('{}'.format((x,y)))
        enemy = self.get_player(token, False)
        me = self.get_player(token, True)
        for p in [me, enemy]:
            if self.winner(p):
                raise GameAlreadyOver('Game already over')
        if enemy.get('turn'):
            raise NotYourTurn('Wait for your turn')
        elif (x, y) in enemy['hits']:
            raise AlreadyHit('{} already hit'.format((x, y)))
        else:
            hit_result = dict(kill=False, hit=False)
            enemy['hits'].append((x, y))
            for ship in enemy['ships']:
                try:
                    if ship.hit(x, y):
                        hit_result['hit'] = True
                        break
                except ShipAlreadyHit:
                    break
                except ShipDead:
                    hit_result['hit'] = True
                    hit_result['kill'] = True
                    break
            if not [s for s in enemy['ships'] if s.lives]:
                me['winner'] = True
                me['turn'] = False
            else:
                enemy['turn'] = True
                me['turn'] = False
            return hit_result

    def ready(self):
        for p in self.players:
            not_ready = [v for v in p['ships_left'].values() if v != 0]
            if not_ready:
                return False
        return True

    def get_status(self, player_token):
        for player in self.players:
            if player['token'] == player_token:
                own = player
            else:
                enemy = player
        return dict(
            own=dict(
                squares=self.get_squares(own, True),
                turn=own.get('turn') or False,
                ships_left=own.get('ships_left'),
                ships=[dict(lives=s.lives, size=s.size)
                    for s in own.get('ships')],
                winner=self.winner(own),
                ),
            enemy=dict(
                squares=self.get_squares(enemy, False),
                turn=enemy.get('turn') or False,
                ships_left=enemy.get('ships_left'),
                ships=[dict(lives=None if s.lives else 0, size=s.size)
                    for s in enemy.get('ships')],
                winner=self.winner(enemy),
                ),
                )

class BattleshipServer(ThreadingMixIn, HTTPServer):
    def add_game(self, game):
        self.game = game

class BattleshipRequestHandler(BaseHTTPRequestHandler):

    protocol_version = 'HTTP/1.1'

    def log_message(self, *args, **kwargs):
        if self.command == 'POST':
            sys.stderr.write('{addr} - - [{datetime}] "POST {path} {req_ver}" {statuscode} {data}\n'.format(
                addr=self.address_string(),
                datetime=self.log_date_time_string(),
                path=self.path,
                req_ver=self.request_version,
                statuscode=args[2],
                data=self.POST_data.decode(),
                ))
        elif self.path.startswith('/gamestatus'):
            pass
        else:
            BaseHTTPRequestHandler.log_message(self, *args, **kwargs)

    def redirect(self, location):
        self.send_response(302)
        self.send_header('Location', location)
        self.send_header('Content-Length', 0)
        self.end_headers()

    def respond_ok(self, data=b'', content_type='text/html; charset=utf-8', age=0):
        self.send_response(200)
        self.send_header('Cache-Control', 'public, max-age={}'.format(age))
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', len(data))
        self.end_headers()
        self.wfile.write(data)

    def respond_notfound(self, data='404'.encode()):
        self.send_response(404)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', len(data))
        self.end_headers()
        self.wfile.write(data)

    def serve_static(self):
        path = 'static/'
        requested_path = self.url_parsed.path[len('/static/'):]
        requested_path = unquote(requested_path)
        requested_path = requested_path.replace('..', '')
        path += requested_path
        with open(path, 'rb') as f:
            fcontent = f.read()
        mime = {
            '.mp3': 'audio/mpeg',
        }
        self.respond_ok(
            fcontent,
            content_type=mime.get(splitext(path)[1]) or 'application/octet-stream'
            )

    def do_GET(self):

        try:
            self.url_parsed = urlparse(self.path)
            if self.url_parsed.path.startswith('/static/'):
                self.serve_static()
            elif self.url_parsed.path == '/':
                index = script_path / 'index.html'
                self.respond_ok(index.open('rb').read())
            elif self.url_parsed.path == '/start':
                start_info = {}
                start_info['token'] = self.server.game.add_player()
                start_info['sounds'] = sound_paths()
                self.respond_ok(json.dumps(start_info).encode())
            elif self.url_parsed.path == '/gamestatus':
                token = float(self.url_parsed.query)
                status = self.server.game.get_status(token)
                self.respond_ok(json.dumps(status).encode())
            else:
                return self.respond_notfound()
        except Exception as e:
            traceback.print_exc()
            self.respond_notfound(str(e).encode())

    def do_POST(self):

        content_length = int(self.headers.get('Content-Length') or 0)
        self.POST_data = self.rfile.read(content_length)

        try:
            self.url_parsed = urlparse(self.path)
            if self.url_parsed.path == '/addship':
                token = float(self.url_parsed.query)
                self.server.game.add_ship(token, **json.loads(self.POST_data.decode()))
                self.respond_ok()
            elif self.url_parsed.path == '/hit':
                token = float(self.url_parsed.query)
                hr = self.server.game.hit(token, **json.loads(self.POST_data.decode()))
                self.respond_ok(json.dumps(hr).encode())
        except Exception as e:
            traceback.print_exc()
            self.respond_notfound(str(e).encode())


if __name__ == '__main__':
    srv = BattleshipServer(('', 8080), BattleshipRequestHandler)
    game = BattleshipGame()
    srv.add_game(game)
    srv.serve_forever()
