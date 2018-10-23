#!/usr/bin/env python3

import config
import json
import lxml  # NOTE(mwek): for pipreqs
import re
import requests

from bs4 import BeautifulSoup
from contextlib import contextmanager
from datetime import datetime, timedelta
from hashlib import sha1


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
                'attachments': [a['href'] for a in n.find('div', class_='newsAttachments').find_all('a')],
            })
        return news

    def get_upcoming_events(self):
        current_month = datetime.today()
        next_month = current_month + timedelta(days=28)
        while next_month.month == current_month.month:
            next_month += timedelta(days=1)
        return self._get_events_for_month(current_month) + self._get_events_for_month(next_month)

    _event_re = re.compile(r'([^<>]+)<br><font[^>]*>(?:Grupa - )?([^<>]+)</font>')

    def _get_events_for_month(self, date):
        r = self._session.get(
            'https://platforma.kidconnect.pl/dashboard/events',
            params={'miesiac': '{0:%d.%m.%Y}'.format(date)},
        )
        r.raise_for_status()

        bs = bs4_parse(r.content)
        events = []
        for d in bs.find_all('div', attrs={'data-trigger': 'focus'}):
            content = d['data-content'].strip()
            if not content:
                continue

            event_date = datetime(day=int(d.text.strip()), month=date.month, year=date.year)
            for evt in self._event_re.findall(content):
                event = {
                    'date': '{0:%Y-%m-%d}'.format(event_date),
                    'title': evt[0].strip(),
                    'group': evt[1].strip(),
                }
                event['id'] = sha1(json.dumps(event, sort_keys=True).encode('utf-8')).hexdigest()
                events.append(event)

        return events


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

    def load(self, *args):
        try:
            with open(self._path, 'r') as f:
                cnt = json.load(f)
            return [cnt.get(a, []) for a in args]
        except FileNotFoundError:
            return [[] for a in args]

    def store(self, **kwargs):
        with open(self._path, 'w') as f:
            json.dump(kwargs, f)


def new_items(current, history):
    history_ids = {h['id'] for h in history}
    return [c for c in current if c['id'] not in history_ids]


if __name__ == '__main__':
    hm = HistoryManager(config.HISTORY_FILE)
    last_seen_news, last_seen_events = hm.load('news', 'events')

    kc = KidConnect()
    with kc.logged_in(config.KIDCONNECT_LOGIN, config.KIDCONNECT_PASSWORD):
        news = kc.get_news()
        events = kc.get_upcoming_events()

    new_news = new_items(news, last_seen_news)
    print('News: {}'.format(new_news))
    new_events = new_items(events, last_seen_events)
    print('Events: {}'.format(new_events))

    ifttt = IFTTT(config.IFTTT_KEY)
    for n in new_news:
        print('New news: {}'.format(n))
        mail_content = '{}<br /><br />{}'.format(n['header'], n['content'])
        if n['attachments']:
            mail_content += '<br />- '.join(['<br /><br />Załączniki / Attachments:'] + n['attachments'])

        ifttt.trigger(
            'kidconnect_news',
            value1=n['title'],
            value2=mail_content,
    )

    for e in new_events:
        ifttt.trigger(
            'kidconnect_event',
            value1=e['date'],
            value2='{}: {}'.format(e['group'], e['title'])
        )

    if new_news or new_events:
        hm.store(news=news, events=events)
