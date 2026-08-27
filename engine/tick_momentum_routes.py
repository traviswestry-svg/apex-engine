"""APEX 69.5.1 routes for observational ES multi-horizon tick momentum."""
from __future__ import annotations
from flask import jsonify, request
from .tick_momentum import VERSION, capability, process_transactions, validate_transactions
from .tick_momentum_store import TickMomentumStore


def register_tick_momentum_routes(app) -> None:
    def store(): return TickMomentumStore()

    @app.get('/api/tick-momentum/capability')
    def tick_momentum_capability(): return jsonify(capability())

    @app.get('/api/tick-momentum/health')
    def tick_momentum_health():
        h=store().health('ES'); h.update({"production_effect":"NONE","execution_authority":False}); return jsonify(h)

    @app.get('/api/tick-momentum/state')
    def tick_momentum_state():
        inst=str(request.args.get('instrument') or 'ES').upper(); s=store().load_state(inst)
        return jsonify({"ok":True,"version":VERSION,"instrument":inst,"state":s,"governance":capability()["governance"]})

    @app.get('/api/tick-momentum/history')
    def tick_momentum_history():
        inst=str(request.args.get('instrument') or 'ES').upper(); limit=int(request.args.get('limit',100))
        rows=store().history(inst,limit); return jsonify({"ok":True,"version":VERSION,"instrument":inst,"count":len(rows),"observations":rows})

    @app.post('/api/tick-momentum/ingest')
    def tick_momentum_ingest():
        body=request.get_json(silent=True) or {}; inst=str(body.get('instrument') or 'ES').upper(); source=str(body.get('source') or '').strip()
        if not source or source.upper() in {'AGGREGATE','BARS','POLYGON_AGGS','MASSIVE_AGGS','UNSPECIFIED'}:
            return jsonify({"ok":False,"version":VERSION,"status":"REJECTED","error":"CONCRETE_TRANSACTION_SOURCE_REQUIRED"}),400
        try:
            records=validate_transactions(body.get('transactions'),instrument=inst); st=store(); before=st.load_state(inst); after,closed=process_transactions(before,records,instrument=inst); st.save(after,closed)
            return jsonify({"ok":True,"version":VERSION,"status":"OBSERVED","source":source,"instrument":inst,"transactions_accepted":len(records),"buckets_closed":len(closed),"alignment":after["alignment"],"horizons":{k:{"state":v["state"],"count":v["count"],"buckets_closed":v["buckets_closed"]} for k,v in after["horizons"].items()},"governance":capability()["governance"]}),201
        except (TypeError,ValueError) as exc:
            return jsonify({"ok":False,"version":VERSION,"status":"REJECTED","error":"TICK_TRANSACTION_VALIDATION_FAILED","detail":str(exc)}),400
