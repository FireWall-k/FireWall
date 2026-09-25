"""운영 관리 명령.

운영(JOBCARD_ENV=prod)에서는 데모 계정을 만들지 않으므로, 사업주 계정은 이 명령으로 만든다.
비밀번호는 명령줄 인자로 받지 않는다(셸 기록·프로세스 목록에 남는다). 입력 프롬프트나 표준입력으로 받는다.

사용 예 (docker compose):
    docker compose exec backend python manage.py create-employer --login itda --org "잇다 보호작업장"
    docker compose exec backend python manage.py set-password --login itda
    echo "$PW" | docker compose exec -T backend python manage.py create-employer --login itda --password-stdin
"""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from auth import hash_password
from database import Base, SessionLocal, apply_pending_columns, engine
from models import Employer

MIN_PASSWORD_LEN = 10


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        pw = sys.stdin.readline().rstrip("\n")
    else:
        pw = getpass.getpass("비밀번호: ")
        if pw != getpass.getpass("비밀번호 확인: "):
            raise SystemExit("두 비밀번호가 다릅니다.")
    if len(pw) < MIN_PASSWORD_LEN:
        raise SystemExit(f"비밀번호는 {MIN_PASSWORD_LEN}자 이상이어야 합니다.")
    return pw


def create_employer(login: str, name: str, org: str, password: str) -> str:
    Base.metadata.create_all(bind=engine)
    apply_pending_columns()
    with SessionLocal() as db:
        if db.scalar(select(Employer).where(Employer.login_id == login)) is not None:
            raise SystemExit(f"이미 있는 아이디입니다: {login}")
        emp = Employer(login_id=login, name=name or login, org_name=org,
                       password_hash=hash_password(password))
        db.add(emp)
        db.commit()
        return emp.id


def set_password(login: str, password: str) -> None:
    with SessionLocal() as db:
        emp = db.scalar(select(Employer).where(Employer.login_id == login))
        if emp is None:
            raise SystemExit(f"없는 아이디입니다: {login}")
        emp.password_hash = hash_password(password)
        db.commit()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="manage.py", description="JOB CARD 운영 관리")
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create-employer", help="사업주 계정 만들기")
    c.add_argument("--login", required=True)
    c.add_argument("--name", default="")
    c.add_argument("--org", default="")
    c.add_argument("--password-stdin", action="store_true")

    p = sub.add_parser("set-password", help="사업주 비밀번호 바꾸기")
    p.add_argument("--login", required=True)
    p.add_argument("--password-stdin", action="store_true")

    args = parser.parse_args(argv)
    pw = _read_password(args.password_stdin)
    if args.cmd == "create-employer":
        emp_id = create_employer(args.login, args.name, args.org, pw)
        print(f"사업주 계정을 만들었습니다: {args.login} ({emp_id})")
    else:
        set_password(args.login, pw)
        print(f"비밀번호를 바꿨습니다: {args.login}")


if __name__ == "__main__":
    main()
