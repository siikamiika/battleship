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
        for p in self.points():
            if p in op:
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
                ships=[],
                ships_left=dict(self._ships_left),
                hits=[],
                token=token))
            return token
        else:
            raise TooManyPlayers('Too many players')

    def get_squares(self, token, own):
        player = self.get_player(token, own)
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
                        if own or ship.lives == 0:
                            sq['txt'] = 'O'
                            sq['cls'].append('ship')
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
        if player['ships_left'][size] <= 0:
            raise OutOfShips('No more ships of size {}'.format(size))
        ship = Ship(coord, size, horizontal)
        for sh in player['ships']:
            if not sh.allowed(ship):
                raise ShipOverlaps()
        player['ships'].append(ship)
        player['ships_left'][size] -= 1

    def hit(self, token, x=None, y=None):
        if not self.ready():
            raise PlayersNotReadyYet()
        enemy = self.get_player(token, False)
        me = self.get_player(token, True)
        if enemy.get('turn'):
            raise NotYourTurn()
        else:
            enemy['turn'] = True
            me['turn'] = False
        if (x, y) in enemy['hits']:
            raise AlreadyHit()
        else:
            enemy['hits'].append((x, y))
            for ship in enemy['ships']:
                try:
                    ship.hit(x, y)
                except ShipDead:
                    pass

    def ready(self):
        for p in self.players:
            print(p)
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
            own=self.get_squares(player_token, True),
            enemy=self.get_squares(player_token, False))

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

    def do_GET(self):

        try:
            self.url_parsed = urlparse(self.path)
            if self.url_parsed.path.startswith('/static/'):
                self.serve_static()
            elif self.url_parsed.path == '/':
                index = script_path / 'index.html'
                self.respond_ok(index.open('rb').read())
            elif self.url_parsed.path == '/start':
                token = self.server.game.add_player()
                self.respond_ok(json.dumps(token).encode())
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
                self.server.game.hit(token, **json.loads(self.POST_data.decode()))
                self.respond_ok()
        except Exception as e:
            traceback.print_exc()
            self.respond_notfound(str(e).encode())


if __name__ == '__main__':
    srv = BattleshipServer(('', 8080), BattleshipRequestHandler)
    game = BattleshipGame()
    srv.add_game(game)
    srv.serve_forever()
