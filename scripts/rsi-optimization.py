"""Offline evaluation CLI. No API call, code generation or production publish."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.adapters.rsi_optimization import assess_opportunities, evaluate_optimization


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['assess', 'evaluate', 'demo-data'])
    parser.add_argument('--stdin', action='store_true', help='JSON object whose values are exact stored UTF-8 strings')
    for name in ['source', 'policy', 'plan', 'candidate', 'measurements']:
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.action == 'demo-data':
        import importlib.util
        spec = importlib.util.spec_from_file_location('optimization_example', ROOT / 'examples/rsi-protocol-v1/optimization_example.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.example()
    else:
        source = json.load(sys.stdin) if args.stdin else None

        def raw(name):
            if source is not None:
                return source[name].encode('utf-8')
            path = getattr(args, name)
            if path is None:
                parser.error('--' + name + ' is required')
            return path.read_bytes()

        if args.action == 'assess':
            result = assess_opportunities(raw('source'), raw('policy'))
        else:
            result = evaluate_optimization(raw('plan'), raw('policy'), raw('candidate'), raw('measurements'))
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
