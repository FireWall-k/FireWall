"""운영 관리 명령.

운영(JOBCARD_ENV=prod)에서는 데모 계정을 만들지 않으므로, 사업주 계정은 이 명령으로 만든다.
비밀번호는 명령줄 인자로 받지 않는다(셸 기록·프로세스 목록에 남는다). 입력 프롬프트나 표준입력으로 받는다.

사용 예 (docker compose):
    docker compose run --rm migrate          # 스키마를 head로(배포 때는 compose가 자동으로 먼저 실행)
    docker compose exec backend python manage.py create-employer --login itda --org "잇다 보호작업장"
    docker compose exec backend python manage.py set-password --login itda
    echo "$PW" | docker compose exec -T backend python manage.py create-employer --login itda --password-stdin
    docker compose exec backend python manage.py purge [--dry-run]   # 보존기간 지난 데이터 삭제(평소에는 scheduler 서비스가 매일 한다)
    docker compose exec backend python manage.py gc-media [--dry-run]  # 고아 사진·TTS만 정리(purge도 함께 한다)
    python manage.py schedule    # 하루 한 번 purge를 도는 루프(compose의 scheduler 서비스가 실행한다)
    python manage.py vapid-keys --out secrets/vapid_private.pem   # 웹 푸시 키 만들기(공개 키만 화면에 보인다)
"""
from __future__ import annotations

import argparse
import getpass
import signal
import sys
import threading

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from auth import hash_password
from codes import new_workplace_code
import db_migrate
from database import SessionLocal
import maintenance
import media
from models import Employer
import retention

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
    """스키마를 head로 올린다. Alembic 도입 전 DB(alembic_version 없음)는 보정 후 baseline으로 stamp한다.

    (2a-0) upgrade 전에 DB 파일을 backups/jobcard-<시각>-<리비전>.db로 복사한다(WAL 체크포인트 뒤). 0007처럼 표를
    다시 만드는 리비전이 중간에 깨져도 되돌릴 수 있게 한다. 복사가 실패하면 upgrade를 하지 않고 멈춘다.
    """
    try:
        backup = db_migrate.backup_before_upgrade()
    except Exception as exc:  # noqa: BLE001 — 무엇이든 백업이 없으면 스키마를 바꾸지 않는다
        raise SystemExit(f"마이그레이션 전 백업을 만들지 못해 멈췄습니다({exc}). "
                         "디스크 공간·폴더 권한을 확인한 뒤 다시 실행해 주세요. DB는 바꾸지 않았습니다.") from exc
    if backup is not None:
        print(f"마이그레이션 전 백업: {backup}")
    report = db_migrate.migrate()
    if report["adopted_legacy"]:
        added = ", ".join(report["repaired_columns"]) or "없음"
        tightened = ", ".join(report["tightened_columns"]) or "없음"
        print(f"기존(Alembic 도입 전) DB를 baseline으로 등록했습니다. 추가한 컬럼: {added}")
        # NOT NULL 조이기는 테이블을 다시 만들고 NULL을 ''로 채운다. logger.info만으로는 compose 출력에
        # 안 보이므로(로깅 미설정) 여기서 직접 적어 운영자가 백업과 대조할 수 있게 한다.
        print(f"NOT NULL로 바꾼 컬럼(기존 NULL은 빈 문자열로 채움): {tightened}")
    print(f"DB 스키마: {report['from_revision'] or '없음'} -> {report['to_revision']}")


def purge(dry_run: bool) -> None:
    """보존기간이 지난 수행 로그·접근 감사 로그와 어느 단계도 쓰지 않는 TTS 파일을 지운다(retention.py).

    요청을 받는 서버 안에 스케줄러를 두지 않는다 — 백엔드 프로세스가 여러 개가 되면 같은 삭제가 겹친다.
    compose의 scheduler 서비스(`manage.py schedule`)가 하루 한 번 같은 일을 한다. 이 명령은 수동 실행·
    dry-run 확인용이다(docs/privacy/data-map.md "삭제 스케줄").
    """
    db_migrate.ensure_schema_ready()
    with SessionLocal() as db:
        report = retention.purge(db, dry_run=dry_run)
    if not dry_run:
        # 손으로 돌린 purge도 마지막 성공으로 남긴다(/health의 purge, maintenance.py).
        maintenance.record_success(report)
    verb = "지울 대상" if dry_run else "지움"
    print(f"수행 로그 {report['performance_logs']}건 {verb} "
          f"(보존 {retention.performance_log_retention_days()}일)")
    print(f"도움 요청 {report.get('help_requests', 0)}건 {verb} "
          f"(보존 {retention.performance_log_retention_days()}일)")
    print(f"접근 감사 로그 {report['access_audit_logs']}건 {verb} "
          f"(보존 {retention.access_audit_retention_days()}일)")
    print(f"DB 백업 사본 {report.get('backup_files', 0)}개 {verb} "
          f"(보존 {retention.backup_retention_days()}일)")
    _print_media_report(report, verb)
    if report.get("wal_checkpointed") is False:
        # 다른 연결이 읽는 중이라 WAL을 비우지 못했다. 지운 데이터가 -wal 파일에 남아 있을 수 있다.
        print("경고: WAL 체크포인트를 끝내지 못했습니다. 잠시 뒤 purge를 다시 실행해 주세요.")


def _print_media_report(report: dict, verb: str) -> None:
    print(f"참조 없는 사진·TTS 레코드 {report['media_records']}건 {verb}")
    print(f"레코드 없는 사진 파일 {report['photo_files']}개 {verb}")
    print(f"레코드 없는 TTS 파일 {report['tts_files']}개 {verb} "
          f"(유예 {media.orphan_grace_hours():g}시간)")


def _print_purge_report(report: dict) -> None:
    print(f"수행 로그 {report['performance_logs']}건 지움, 접근 감사 로그 {report['access_audit_logs']}건 지움, "
          f"DB 백업 사본 {report.get('backup_files', 0)}개 지움")
    _print_media_report(report, "지움")
    if report.get("wal_checkpointed") is False:
        print("경고: WAL 체크포인트를 끝내지 못했습니다. 다음 실행에서 다시 합니다.")


def schedule() -> None:
    """purge를 주기마다(기본 24시간, PURGE_INTERVAL_HOURS) 돌리는 루프. compose의 scheduler 서비스가 실행한다.

    컨테이너의 PID 1은 핸들러 없는 SIGTERM을 무시한다(docker stop이 10초 뒤 강제 종료). 그래서 SIGTERM·SIGINT를
    받으면 stop 이벤트를 세워 대기 중이든 아니든 곧바로 끝나게 한다. 삭제 도중이면 그 한 번을 마치고 끝난다.
    """
    stop = threading.Event()

    def _stop(_signum, _frame) -> None:
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _stop)
        except (ValueError, OSError):  # 메인 스레드가 아닐 때(테스트) 등
            pass
    print(f"보존기간 삭제 스케줄 시작: {maintenance.default_interval_hours():g}시간마다, "
          f"상태 파일 {maintenance.status_path()}", flush=True)
    maintenance.loop(stop, on_report=_print_purge_report)
    print("보존기간 삭제 스케줄 종료", flush=True)


def gc_media(dry_run: bool) -> None:
    """고아 사진·TTS 정리(media.gc)만 따로 돌린다. purge도 매번 같은 정리를 하므로, 보통은 scheduler의 매일 purge로 충분하다.

    디스크가 갑자기 찼거나 마이그레이션(0004) 직후 옛 파일을 바로 확인하고 싶을 때 쓴다. --dry-run으로 먼저 본다.
    """
    db_migrate.ensure_schema_ready()
    with SessionLocal() as db:
        report = media.gc(db, dry_run=dry_run)
    verb = "지울 대상(dry-run)" if dry_run else "지움"
    _print_media_report(report, verb)


def vapid_keys(out: str, force: bool = False) -> str:
    """웹 푸시(VAPID) P-256 키 한 쌍을 만든다(2c). 개인 키는 out 파일(PEM, 소유자만 읽기)에만 쓰고 화면에 내지 않는다.

    돌려주는 공개 키(base64url, 압축 안 한 점)를 VAPID_PUBLIC_KEY에, 파일 경로를 VAPID_PRIVATE_KEY_FILE에 둔다.
    키를 바꾸면 사업주 기기의 기존 구독은 모두 다시 켜야 한다(그래서 있는 파일은 --force 없이 덮어쓰지 않는다).
    """
    import base64
    import os

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    if os.path.exists(out) and not force:
        raise SystemExit(f"이미 있는 파일이에요: {out} (바꾸려면 --force. 바꾸면 알림 구독을 모두 다시 켜야 해요)")
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    raw = key.public_key().public_bytes(serialization.Encoding.X962,
                                        serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


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

    g = sub.add_parser("purge", help="보존기간 지난 수행 로그·접근 감사 로그·미참조 TTS 파일 삭제")
    g.add_argument("--dry-run", action="store_true", help="지우지 않고 개수만 보여 주기")

    sub.add_parser("schedule", help="하루 한 번 purge를 도는 루프(compose scheduler 서비스용)")

    m = sub.add_parser("gc-media", help="레코드 없는 사진·TTS 파일과 어느 단계도 쓰지 않는 레코드 삭제")
    m.add_argument("--dry-run", action="store_true", help="지우지 않고 개수만 보여 주기")

    v = sub.add_parser("vapid-keys", help="웹 푸시 키 만들기(개인 키는 파일로만, 공개 키를 출력)")
    v.add_argument("--out", required=True, help="개인 키 PEM을 쓸 파일(VAPID_PRIVATE_KEY_FILE)")
    v.add_argument("--force", action="store_true", help="있는 파일을 덮어쓰기")

    args = parser.parse_args(argv)
    if args.cmd == "vapid-keys":
        pub = vapid_keys(args.out, args.force)
        print(f"개인 키를 썼습니다: {args.out}")
        print(f"VAPID_PUBLIC_KEY={pub}")
        print(f"VAPID_PRIVATE_KEY_FILE={args.out}")
        return
    if args.cmd == "migrate":
        migrate()
        return
    if args.cmd == "purge":
        purge(args.dry_run)
        return
    if args.cmd == "schedule":
        schedule()
        return
    if args.cmd == "gc-media":
        gc_media(args.dry_run)
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
