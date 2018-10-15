#!/usr/bin/env python3

import config
import json
import lxml  # NOTE(mwek): for pipreqs
import requests

from bs4 import BeautifulSoup
from contextlib import contextmanager


def bs4_parse(content):
    return BeautifulSoup(content, 'lxml')


class KidConnect:
    def __init__(self):
        self._session = requests.Session()
        self._session.headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/69.0.3497.100 Safari/537.36'

    def login(self, email, password):
        # Step 1: get the CSRF token
        r = self._session.get('https://platforma.kidconnect.pl/')
        r.raise_for_status()
        bs = bs4_parse(r.content)
        token = bs.find('input', attrs={'name': '_token'})['value']

        # Step 2: log in the request
        r = self._session.post(
            'https://platforma.kidconnect.pl/login',
            headers={'referer': 'https://platforma.kidconnect.pl/'},
            data={'mail': email, 'password': password, '_token': token})
        r.raise_for_status()
        assert b'Weksej Maciej' in r.content, r

    def logout(self):
        self._session.get('https://platforma.kidconnect.pl/logout')

    @contextmanager
    def logged_in(self, email, password):
        self.login(email, password)
        try:
            yield
        finally:
            self.logout()

    def get_news(self, page=1):
        r = self._session.get(
            'https://platforma.kidconnect.pl/dashboard/filterrednews',
            params={'page': page, 'filterType': 'all'})
        r.raise_for_status()

        bs = bs4_parse(r.content)
        news = []
        for n in bs.find_all('div', class_='aktualnosc'):
            news.append({
                'id': n['data-aktualnoscid'],
                'title': n.find('span', class_='tytul_nowosci').get_text().strip(),
                'header': n.find('small').get_text().strip(),
                'content': n.find('div', class_='tresc-aktualnosci').get_text().strip(),
            })
        return news


class IFTTT:
    def __init__(self, key):
        self._key = key

    def trigger(self, event, value1=None, value2=None, value3=None):
        data = {}
        if value1:
            data['value1'] = value1
        if value2:
            data['value2'] = value2
        if value3:
            data['value3'] = value3

        return requests.post(
            'https://maker.ifttt.com/trigger/{}/with/key/{}'.format(event, self._key),
            json=data)


class HistoryManager:
    def __init__(self, path):
        self._path = path

    def load(self):
        try:
            with open(self._path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return []

    def store(self, content):
        with open(self._path, 'w') as f:
            json.dump(content, f)


if __name__ == '__main__':
    hm = HistoryManager(config.HISTORY_FILE)
    last_seen_news = hm.load()

    kc = KidConnect()
    with kc.logged_in(config.KIDCONNECT_LOGIN, config.KIDCONNECT_PASSWORD):
        news = kc.get_news()

    old_news_id = {n['id'] for n in last_seen_news}
    new_news = [n for n in news if n['id'] not in old_news_id]

    ifttt = IFTTT(config.IFTTT_KEY)
    for n in new_news:
        print('New news: {}'.format(n))
        ifttt.trigger(
            'kidconnect_news',
            value1=n['title'],
            value2=n['header'],
            value3=n['content'].replace('\n', '<br />\n'))

    hm.store(news)
