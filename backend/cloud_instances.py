"""CLI for the same Docker logic the web console uses (docker_manager.py).

Commands (use `python` on Windows, `python3` on Linux/macOS):
  python cloud_instances.py create --name vm1 --os ubuntu --cpu 2 --ram 2048 --storage 20
  python cloud_instances.py create --name vm2 --os debian --cpu 1 --ram 1024 --storage 10
  python cloud_instances.py start|stop|restart vm1
  python cloud_instances.py terminate vm1              # keeps the data volume
  python cloud_instances.py terminate vm1 --delete-data
  python cloud_instances.py list
Note: instances created here are standalone; the web console manages the ones it creates itself.
"""
import argparse

import docker_manager as dm


def main():
    p = argparse.ArgumentParser(description="Docker Cloud Instance Manager")
    sub = p.add_subparsers(dest="action", required=True)
    c = sub.add_parser("create")
    c.add_argument("--name", required=True)
    c.add_argument("--os", choices=dm.IMAGES, default="ubuntu")
    c.add_argument("--cpu", type=float, default=1)
    c.add_argument("--ram", type=int, default=1024, help="MB")
    c.add_argument("--storage", type=int, default=10, help="GB (not enforced)")
    for a in ("start", "stop", "restart"):
        sub.add_parser(a).add_argument("name")
    t = sub.add_parser("terminate")
    t.add_argument("name")
    t.add_argument("--delete-data", action="store_true")
    sub.add_parser("list")
    args = p.parse_args()
    try:
        if args.action == "create":
            r = dm.create_instance(args.name, args.os, args.cpu, args.ram, args.storage)
            print(f"Created {args.name} ({r['id']}) status={r['status']} volume={r['volume']} -> /data")
        elif args.action in ("start", "stop", "restart"):
            dm.control(args.name, args.action)
            print(f"{args.name}: {args.action} OK")
        elif args.action == "terminate":
            dm.remove(args.name, args.delete_data)
            print(f"{args.name} terminated" + (" (data deleted)" if args.delete_data else f" (data kept in volume {args.name}-data)"))
        else:
            rows = dm.statuses()
            if not rows:
                print("No cloud instances found.")
            print(f"{'NAME':<30} {'STATUS':<10} {'IP':<16} IMAGE")
            for n, s in rows.items():
                print(f"{n:<30} {s['status']:<10} {s['ip']:<16} {s['image']}")
    except dm.DockerError as exc:
        print(f"Error: {exc}")


if __name__ == "__main__":
    main()
