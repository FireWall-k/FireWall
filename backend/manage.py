"""운영 관리 명령.

운영(JOBCARD_ENV=prod)에서는 데모 계정을 만들지 않으므로, 사업주 계정은 이 명령으로 만든다.
비밀번호는 명령줄 인자로 받지 않는다(셸 기록·프로세스 목록에 남는다). 입력 프롬프트나 표준입력으로 받는다.

사용 예 (docker compose):
    docker compose run --rm migrate          # 스키마를 head로(배포 때는 compose가 자동으로 먼저 실행)
    docker compose exec backend python manage.py create-employer --login itda --org "잇다 보호작업장"
    docker compose exec backend python manage.py set-password --login itda
    echo "$PW" | docker compose exec -T backend python manage.py create-employer --login itda --password-stdin
"""
from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from auth import hash_password
from codes import new_workplace_code
import db_migrate
from database import SessionLocal
from models import Employer

MIN_PASSWORD_LEN = 8
# 사업장 코드(약 10억 가지)가 기존 사업장과 겹칠 때 다시 뽑는 횟수. 실제로는 거의 한 번에 끝난다.
_WORKPLACE_CODE_ATTEMPTS = 5


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


def create_employer(login: str, name: str, org: str, password: str) -> tuple[str, str]:
    # 운영에서는 migrate 서비스가 먼저 돌았어야 한다(아니면 이유를 적고 멈춘다). 개발이면 여기서 올린다.
    db_migrate.ensure_schema_ready()
    password_hash = hash_password(password)
    with SessionLocal() as db:
        for _ in range(_WORKPLACE_CODE_ATTEMPTS):
            if db.scalar(select(Employer).where(Employer.login_id == login)) is not None:
                raise SystemExit(f"이미 있는 아이디입니다: {login}")
            # 사업장 코드는 서버가 만든다(codes.py). 근로자 기기에 입력해야 하므로 바로 보여 준다.
            emp = Employer(login_id=login, name=name or login, org_name=org,
                           password_hash=password_hash, workplace_code=new_workplace_code())
            db.add(emp)
            try:
                db.commit()
            except IntegrityError:
                # 사업장 코드가 기존 사업장과 우연히 겹쳤거나(전역 unique), 같은 아이디가 동시에
                # 만들어졌다. 롤백 후 아이디부터 다시 확인하고, 아이디 문제가 아니면 새 코드로 재시도한다.
                db.rollback()
                continue
            return emp.id, emp.workplace_code
    raise SystemExit("사업장 코드를 만들지 못했습니다. 다시 시도해 주세요.")


def set_password(login: str, password: str) -> None:
    with SessionLocal() as db:
        emp = db.scalar(select(Employer).where(Employer.login_id == login))
        if emp is None:
            raise SystemExit(f"없는 아이디입니다: {login}")
        emp.password_hash = hash_password(password)
        db.commit()


def migrate() -> None:
    """스키마를 head로 올린다. Alembic 도입 전 DB(alembic_version 없음)는 보정 후 baseline으로 stamp한다."""
    report = db_migrate.migrate()
    if report["adopted_legacy"]:
        added = ", ".join(report["repaired_columns"]) or "없음"
        print(f"기존(Alembic 도입 전) DB를 baseline으로 등록했습니다. 추가한 컬럼: {added}")
    print(f"DB 스키마: {report['from_revision'] or '없음'} -> {report['to_revision']}")


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

    sub.add_parser("migrate", help="DB 스키마를 최신(head)으로 올리기 — 배포 때 migrate 서비스가 실행")

    args = parser.parse_args(argv)
    if args.cmd == "migrate":
        migrate()
        return
    pw = _read_password(args.password_stdin)
    if args.cmd == "create-employer":
        emp_id, workplace_code = create_employer(args.login, args.name, args.org, pw)
        print(f"사업주 계정을 만들었습니다: {args.login} ({emp_id})")
        print(f"사업장 코드: {workplace_code} (근로자 기기의 로그인 화면에 한 번 입력해 두세요)")
    else:
        set_password(args.login, pw)
        print(f"비밀번호를 바꿨습니다: {args.login}")


if __name__ == "__main__":
    main()
