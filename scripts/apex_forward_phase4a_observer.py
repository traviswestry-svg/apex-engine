"""Phase 4A read-only external Render deployment observer (no signing, no GO)."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from engine.forward_provenance_render_observer import (
    ObservationError, collect, render_http_get,
)


def fixture_get(path, params, doc):
    # Local simulations must never be represented as observations from Render.
    if path.endswith('/deploys'):
        pages = doc.get('pages', [])
        index = 0 if 'cursor' not in params else next(
            (i + 1 for i, p in enumerate(pages)
             if p and p[-1].get('cursor') == params['cursor']), -1)
        if not (0 <= index < len(pages)):
            return []
        return pages[index]
    return doc.get('service')


def atomic_create(path: Path, data: bytes) -> None:
    """Create new result; never overwrite a preexisting evidence artifact."""
    if path.is_symlink() or path.exists():
        raise ObservationError('OUTPUT_EXISTS_OR_SYMLINK')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except FileExistsError:
        raise ObservationError('OUTPUT_EXISTS_OR_SYMLINK') from None


def run(argv=None) -> tuple[dict, int]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service-id', required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--fixture', help='Offline simulation JSON; never real authentication')
    source.add_argument('--live-render-api', action='store_true', help='Authenticated GET only; requires externally operated collector')
    parser.add_argument('--out', help='New JSON evidence file; existing files cannot be overwritten')
    parser.add_argument('--max-pages', type=int, default=10)
    parser.add_argument('--as-of', help='UTC time for deterministic fixtures')
    args = parser.parse_args(argv)
    try:
        if args.fixture:
            doc = json.loads(Path(args.fixture).read_text(encoding='utf-8'))
            get = lambda path, params: fixture_get(path, params, doc)
            capture = 'OFFLINE_FIXTURE_NOT_OBSERVED'
        else:
            token = os.getenv('RENDER_API_KEY')
            get = render_http_get(token)
            capture = 'RENDER_API_READ_ONLY_RESPONSE'
        result = collect(args.service_id, get, observed_at=args.as_of, max_pages=args.max_pages)
        result['capture_mode'] = capture
        result['independent_collector_identity'] = 'NOT_ATTESTED'
        result['production_activation_authorized'] = False
        result['promotion_authority'] = 'NONE'
        if args.out:
            atomic_create(Path(args.out), (json.dumps(result, indent=2, sort_keys=True) + '\n').encode())
        return result, 0
    except (ObservationError, OSError, ValueError, TypeError, json.JSONDecodeError) as e:
        code = str(e) if isinstance(e, ObservationError) else type(e).__name__
        return {
            'ok': False, 'phase': '4A', 'reason': code,
            'verdict': 'NO_GO', 'production_activation_authorized': False,
            'promotion_authority': 'NONE', 'process_identity': 'NOT_AUTHENTICATED',
        }, 2


def main():
    report, code = run()
    print(json.dumps(report, indent=2, sort_keys=True))
    return code

if __name__ == '__main__':
    raise SystemExit(main())
