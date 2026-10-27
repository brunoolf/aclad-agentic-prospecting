"""Consent-bounded sent-mail sampling; only reviewed summaries become active style."""
from __future__ import annotations

from datetime import timedelta
from statistics import median
from uuid import uuid4

from .models import Event, GateError, Payload, Record, now_utc, payload, utc
from .store import Store


def style_presets() -> list[Payload]:
    return [
        {'id': 'direct', 'tone': 'direto e cordial', 'length': 'curto', 'formality': 'profissional próximo',
         'example': 'Olá! Vi a expansão da operação. Vale conversar sobre como o NetSuite pode apoiar essa fase?'},
        {'id': 'consultative', 'tone': 'consultivo e curioso', 'length': 'médio', 'formality': 'profissional próximo',
         'example': 'Olá! A expansão anunciada pode trazer desafios de consolidação. Essa é uma prioridade para vocês? Podemos conversar sobre o contexto antes de sugerir algo.'},
        {'id': 'formal', 'tone': 'objetivo e respeitoso', 'length': 'curto', 'formality': 'formal',
         'example': 'Bom dia. Gostaria de entender se a consolidação da operação é uma prioridade e avaliar se faz sentido apresentar uma abordagem com NetSuite.'},
    ]


def _sent_connection(store: Store, connection_id: str, identity: str) -> Record:
    matches = [row for row in store.list('connection')
               if row.data.get('capability', {}).get('connection_id') == connection_id
               and row.data['capability'].get('operation') == 'email.read']
    if len(matches) != 1:
        raise GateError('style_sent_access_required')
    row = matches[0]
    cap = row.data['capability']
    if (not isinstance(identity, str) or '@' not in identity or not identity.strip()
            or row.data.get('account_identity') != identity
            or row.data.get('supports_sent') is not True
            or cap.get('visibility') != 'visible' or cap.get('verification') != 'verified'
            or cap.get('auth') != 'authenticated' or cap.get('permission') != 'allowed'
            or cap.get('cost') != 'free'):
        raise GateError('style_sent_access_required', 'Verify your own identity and free sent-mail read access first.')
    return row


def prepare_style_sample(store: Store, connection_id: str, identity: str,
                         approved: bool, limit: int = 10) -> Record:
    if approved is not True:
        raise GateError('style_sample_consent_required')
    if type(limit) is not int or not 1 <= limit <= 10:
        raise GateError('invalid_style_sample_limit')
    with store.transaction():
        connection = _sent_connection(store, connection_id, identity)
        now = utc(now_utc())
        data = {'type': 'style_sample_request', 'status': 'prepared', 'connection_id': connection_id,
                'identity': identity, 'approved': True, 'approved_at': now.isoformat(),
                'expires_at': (now + timedelta(hours=24)).isoformat(),
                'connection_revision': connection.revision,
                'query': {'folder': 'sent', 'sender': identity, 'limit': limit,
                          'since': (now - timedelta(days=90)).isoformat(), 'until': now.isoformat(),
                          'purpose': 'prospecting', 'professional_only': True,
                          'exclude_internal': True, 'exclude_automated': True},
                'retention': 'summarized_patterns_and_minimal_private_references_only'}
        record = store.put('analysis', 'style-request-' + uuid4().hex, data, None)
        store.record_event(Event(str(uuid4()), record.id, 'style.sample_consented', now_utc(), {'limit': limit}))
        return record


def _summarize(bodies: list[str]) -> Payload:
    if not bodies:
        return {}
    words = median(len(body.split()) for body in bodies)
    formal = sum(body.casefold().startswith(('prezado', 'prezada', 'estimado', 'dear', 'bom dia')) for body in bodies)
    questions = sum('?' in body for body in bodies)
    return {'tone': 'profissional; sugestão heurística para revisão',
            'length': 'curto' if words <= 80 else 'médio' if words <= 180 else 'longo',
            'formality': 'formal' if formal > len(bodies) / 2 else 'profissional próximo',
            'cta': 'pergunta simples' if questions > len(bodies) / 2 else 'convite a revisar',
            'greeting': 'saudação profissional'}


def record_style_sample(store: Store, request_id: str, messages: list[Payload]) -> Record:
    """Consume at most the approved limit; raw bodies are transient and never persisted."""
    with store.transaction():
        request = store.get('analysis', request_id)
        if (not request or request.data.get('type') != 'style_sample_request'
                or request.data.get('status') != 'prepared' or request.data.get('approved') is not True):
            raise GateError('invalid_style_sample_request')
        data = request.data
        connection = _sent_connection(store, data['connection_id'], data['identity'])
        if connection.revision != data['connection_revision'] or utc(now_utc()) > utc(data['expires_at']):
            raise GateError('style_sample_request_stale')
        if not isinstance(messages, list) or len(messages) > data['query']['limit']:
            raise GateError('invalid_style_sample_limit')
        bodies, references, seen = [], [], set()
        domain = data['identity'].rsplit('@', 1)[1].casefold()
        for raw in messages:
            message = payload(raw)
            if (message.get('connection_id') != data['connection_id']
                    or message.get('sender') != data['identity']):
                raise GateError('style_sample_identity_mismatch')
            # Missing classification is not permission to ingest personal/internal mail.
            if (message.get('folder') != 'sent' or message.get('professional') is not True
                    or message.get('purpose') != 'prospecting' or message.get('internal') is not False
                    or message.get('automated') is not False):
                continue
            recipients = message.get('recipients')
            if (not isinstance(recipients, list) or not recipients
                    or any(not isinstance(address, str) or '@' not in address
                           or address.rsplit('@', 1)[1].casefold() == domain for address in recipients)):
                continue
            try:
                sent = utc(message.get('sent_at'))
            except GateError:
                continue
            if not utc(data['query']['since']) <= sent <= utc(data['query']['until']):
                continue
            identifier, body = message.get('id'), message.get('body')
            if (not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 512
                    or identifier in seen or not isinstance(body, str) or not body.strip() or len(body) > 100_000):
                continue
            seen.add(identifier)
            bodies.append(body)
            references.append({'id': identifier, 'sent_at': message['sent_at']})
        sample = store.put('analysis', 'style-sample-' + uuid4().hex,
            {'type': 'style_sample', 'request_id': request.id, 'status': 'needs_review',
             'sample_count': len(bodies), 'excluded_count': len(messages) - len(bodies),
             'references': references, 'patterns': _summarize(bodies), 'created_at': now_utc(),
             'limitation': 'Amostra pequena; padrões heurísticos precisam da sua revisão.'}, None)
        store.put('analysis', request.id, dict(data, status='consumed', sample_id=sample.id), request.revision)
        store.record_event(Event(str(uuid4()), sample.id, 'style.sample_summarized', now_utc(),
                                 {'sample_count': len(bodies)}))
        return sample


def approve_style(store: Store, sample_id: str, revision: int, patterns: Payload,
                  approved_by: str) -> Record:
    patterns = payload(patterns)
    allowed = {'tone', 'length', 'formality', 'greeting', 'cta', 'signature'}
    if (not patterns or set(patterns) - allowed
            or any(not isinstance(v, str) or not v.strip() or len(v) > 240 for v in patterns.values())
            or not isinstance(approved_by, str) or not approved_by.strip()):
        raise GateError('invalid_style_approval')
    with store.transaction():
        sample = store.get('analysis', sample_id)
        if (not sample or sample.data.get('type') != 'style_sample'
                or sample.revision != revision or sample.data.get('status') != 'needs_review'
                or sample.data.get('sample_count', 0) < 1):
            raise GateError('style_review_required')
        data = {'status': 'active', 'sample_id': sample_id, 'sample_revision': revision,
                'patterns': patterns, 'approved_by': approved_by, 'approved_at': now_utc()}
        old = store.get('profile', 'writing-style')
        result = store.put('profile', 'writing-style', data, old.revision if old else None)
        store.put('analysis', sample.id, dict(sample.data, status='approved'), sample.revision)
        store.record_event(Event(str(uuid4()), result.id, 'style.approved', now_utc(), {'sample_id': sample_id}))
        return result
