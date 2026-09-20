#!/usr/bin/env python3
"""testar.py -- corre a camada de testes do projeto e carimba verde se passar.

Peca central do Bulletproof. Le os stacks do .framework-version (ou deteta-os) e
corre o comando de teste de cada um (override em .framework-version["tests"][stack],
senao um default por stack). Depois:
  - todas verdes   -> chama mark-green.sh (o Exit Lock passa a deixar commitar; o
                      mark-green e' quem regista o test_green no ledger).
  - alguma vermelha -> regista test_red no ledger (a falha/bug apanhado) e reporta;
                      NAO carimba (o Exit Lock continua a bloquear commits de codigo).

Uso: python3 testar.py [dir]   (default: diretorio atual)
So age em projetos geridos pelo plugin (a porta fv.py).
Override por env (testes): BULLETPROOF_STATE, BULLETPROOF_LEDGER.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fv as gate
import stacks as stackmod

DEFAULT_TEST_CMD = {
    "python": "pytest -q",
    "node": "npm test",
    "go": "go test ./...",
    "rust": "cargo test",
    "ruby": "bundle exec rake test",
}


def fingerprint(root):
    try:
        return subprocess.run(["bash", os.path.join(HERE, "exit-lock-fp.sh"), root],
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def log_red(root, detail, seed):
    """Regista a falha apanhada no ledger. Best-effort, nunca rebenta."""
    try:
        import ledger
        ledger.record(event="test_red", gate="testar", project=root,
                      reason="tests_failed", incident_seed=seed, detail=detail)
    except Exception:
        pass


def promote_to_active(root):
    """No primeiro verde, promove o projeto de 'bootstrapping' para 'active' no
    .framework-version, armando o Exit Lock. Idempotente (se ja active, no-op).
    Best-effort: se falhar, o carimbo verde acontece na mesma."""
    path = os.path.join(root, ".framework-version")
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("status") == "active":
            return False
        data["status"] = "active"
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return True
    except Exception:
        return False


def main(argv):
    start = os.path.abspath(argv[0]) if argv else os.getcwd()
    fvdata = gate.managed_project(start)
    if fvdata is None:
        print("testar: this project is not adopted by Bulletproof. "
              "Run /bulletproof:framework-init first.")
        return 2

    root = gate.root_of(start) or start
    declared = fvdata.get("stacks") or stackmod.detect(root)
    overrides = fvdata.get("tests") if isinstance(fvdata.get("tests"), dict) else {}

    if not declared:
        print("testar: no stack declared or detected. Add one "
              "(/bulletproof:framework-init --stack <s>) or a manifest file.")
        return 2

    plan = []
    for s in declared:
        cmd = overrides.get(s) or DEFAULT_TEST_CMD.get(s)
        if cmd:
            plan.append((s, cmd))
        else:
            print("testar: warning, no test command for stack '%s' "
                  "(set one in .framework-version[\"tests\"][\"%s\"])." % (s, s))

    if not plan:
        print("testar: no test command to run.")
        return 2

    failures = []
    for s, cmd in plan:
        print(">> [%s] %s" % (s, cmd))
        if subprocess.run(cmd, shell=True, cwd=root).returncode != 0:
            failures.append({"stack": s, "cmd": cmd})

    if failures:
        log_red(root, {"failed": failures}, fingerprint(root))
        print("\ntestar: RED. %d of %d test suite(s) failed. Nothing stamped; the Exit "
              "Lock keeps blocking code commits. Fix it and run again."
              % (len(failures), len(plan)))
        return 1

    # verde: promove a 'active' no 1o verde (arma o Exit Lock) e carimba via mark-green
    promoted = promote_to_active(root)
    subprocess.run(["bash", os.path.join(HERE, "mark-green.sh"), root])
    print("\ntestar: GREEN. Every test suite passed. Green stamped; code commits are "
          "now allowed.")
    if promoted:
        print("  project promoted to 'active': the Exit Lock now polices code commits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
