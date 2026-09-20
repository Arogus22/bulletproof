#!/usr/bin/env python3
"""ledger.py -- registo de intervencoes do Bulletproof (append-only, JSONL).

Peca-base GENERICA: qualquer hook/gate lhe pode chamar para registar quando
travou ou apanhou algo, para mais tarde se auditar "quantas vezes nos safou".
Global (um so ficheiro, com campo `project` para filtrar por projeto), em
~/.claude/state/bulletproof/ledger.jsonl -- caminho absoluto, sobrevive a updates
do plugin. Best-effort: NUNCA levanta (o chamador nao pode partir por causa disto).

Dois usos:
  modulo:  import ledger; ledger.record(event="block", gate="exit_lock", project=..., ...)
  CLI:     python3 ledger.py <event> <gate> <project> [--reason R] [--session S] \
                    [--incident-seed X] [--detail JSON]

Eventos previstos: "block" (um gate travou uma acao), "test_red" (um teste apanhou
uma falha real), "test_green" (testes passaram; serve de denominador). O campo
`event` etiqueta-os para o relatorio nunca somar bloqueios com bugs apanhados.

Override por env (para testes, nunca tocam no estado real):
  BULLETPROOF_LEDGER -- caminho do ficheiro do ledger.
"""
import datetime
import hashlib
import json
import os


def _ledger_path():
    return os.environ.get("BULLETPROOF_LEDGER") or \
        os.path.expanduser("~/.claude/state/bulletproof/ledger.jsonl")


def _incident(project, seed):
    """Hash estavel p/ agrupar retries do mesmo incidente (ex.: 3 tentativas de
    commit do mesmo codigo nao-verde = 1 incidente). seed = fingerprint quando ha."""
    base = "%s|%s" % (project or "", seed or "")
    return hashlib.sha256(base.encode()).hexdigest()[:12]


def record(event, gate, project, reason=None, incident_seed=None,
           session=None, detail=None):
    """Faz append de uma linha ao ledger. Best-effort, nunca levanta; devolve bool."""
    try:
        rec = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "event": event,
            "gate": gate,
            "project": project,
            "incident": _incident(project, incident_seed),
        }
        if reason is not None:
            rec["reason"] = reason
        if session is not None:
            rec["session"] = session
        if detail is not None:
            rec["detail"] = detail
        path = _ledger_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # append de uma linha < 4KB e' atomico em POSIX: varias sessoes do Claude
        # a escrever ao mesmo tempo nao corrompem o ficheiro.
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def _main(argv):
    import argparse
    p = argparse.ArgumentParser(description="append one intervention to the ledger")
    p.add_argument("event")
    p.add_argument("gate")
    p.add_argument("project")
    p.add_argument("--reason")
    p.add_argument("--session")
    p.add_argument("--incident-seed", dest="incident_seed")
    p.add_argument("--detail", help="JSON with extra detail")
    a = p.parse_args(argv)
    detail = None
    if a.detail:
        try:
            detail = json.loads(a.detail)
        except Exception:
            detail = {"raw": a.detail}
    ok = record(event=a.event, gate=a.gate, project=a.project, reason=a.reason,
                incident_seed=a.incident_seed, session=a.session, detail=detail)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    import sys
    _main(sys.argv[1:])
