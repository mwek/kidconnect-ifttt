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
from itertools import count


def bs4_parse(content):
    return BeautifulSoup(content, 'lxml')


def nl2br(s):
    return s.replace('\r\n', '<br />').replace('\n', '<br />').replace('<br />', '<br />\n')


def stable_id(d):
    return sha1(json.dumps(d, sort_keys=True).encode('utf-8')).hexdigest()


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

    def get_news(self):
        all_news = []
        for page in count(1):
            page_news = self._get_news(page)
            if not page_news:
                break
            all_news += page_news

        return sorted(all_news, key=lambda n: n['date'], reverse=True)

    def _get_news(self, page):
        r = self._session.get(
            'https://platforma.kidconnect.pl/dashboard/filterrednews',
            params={'page': page, 'filterType': 'all'})
        r.raise_for_status()

        bs = bs4_parse(r.content)
        return [self._parse_news(n) for n in bs.find_all('div', class_='aktualnosc')]

    _date_re = re.compile(r'Data: ([^,]+)')

    def _parse_news(self, n):
        parsed_news = {
            'id': n['data-aktualnoscid'],
            'title': n.find('span', class_='tytul_nowosci').get_text().strip(),
            'header': n.find('small').get_text().strip(),
            'content': nl2br(n.find('div', class_='tresc-aktualnosci').get_text().strip()),
        }

        news_date_text = self._date_re.search(parsed_news['header']).group(1)
        news_date = datetime.strptime(news_date_text, '%d.%m.%Y %H:%M')

        parsed_news['date'] = '{0:%Y-%m-%d %H:%M}'.format(news_date)

        attachments = n.find('div', class_='newsAttachments')
        if attachments:
            parsed_news['attachments'] = [a['href'] for a in attachments.find_all('a')]
        else:
            parsed_news['attachments'] = []

        return parsed_news

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
                event['id'] = stable_id(event)
                events.append(event)

        return events

    def get_conversations(self, ids):
        return {id: self._get_conversation(id) for id in ids}

    def _get_conversation(self, id):
        r = self._session.get(
            'https://platforma.kidconnect.pl/conversation/messages/getlastfive',
            params={
                'currentLoadedMessages': 1000,  # To make the API return more than 5 messages
                'conversationId': id,
                'messagesIdArray': 'a:1:{i:0;i:0;}',
            }
        )
        r.raise_for_status()

        bs = bs4_parse(r.json()['view'])
        return [self._parse_message(m) for m in bs.find_all('div', class_='pointer')]

    def _parse_message(self, bs):
        message = {}
        header = bs.find('div', class_='card-header')
        message['author'] = header.find('b').text.strip()
        message['date'] = header.find('small').text.strip()
        message['content'] = nl2br(bs.find('div', class_='card-body').text.strip())
        message['id'] = stable_id(message)
        return message


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
            return [cnt.get(a) for a in args]
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
    last_seen_news, last_seen_events, last_seen_conversations = hm.load('news', 'events', 'conversations')

    kc = KidConnect()
    with kc.logged_in(config.KIDCONNECT_LOGIN, config.KIDCONNECT_PASSWORD):
        news = kc.get_news()
        events = kc.get_upcoming_events()
        conversations = kc.get_conversations(config.CONVERSATIONS.keys())

    new_news = new_items(news, last_seen_news or [])
    print('News: {}'.format(new_news))
    new_events = new_items(events, last_seen_events or [])
    print('Events: {}'.format(new_events))
    new_conversations = {
        id: new_items(messages, (last_seen_conversations or {}).get(str(id), []))
        for id, messages in conversations.items()
    }
    print('Conversations: {}'.format(new_conversations))

    ifttt = IFTTT(config.IFTTT_KEY)
    for n in new_news:
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

    for cid, messages in new_conversations.items():
        for m in messages:
            ifttt.trigger(
                'kidconnect_message',
                value1='[{}] New message from {}'.format(config.CONVERSATIONS[cid], m['author']),
                value2='Author: {}<br />Date: {}<br /><br />{}<br /><br />https://platforma.kidconnect.pl/conversation/{}'.format(
                    m['author'], m['date'], m['content'], cid
                )
            )

    if new_news or new_events or any(new_conversations.values()):
        hm.store(news=news, events=events, conversations=conversations)
