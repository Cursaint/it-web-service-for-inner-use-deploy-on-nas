from datetime import date, datetime
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from database import get_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="template")

Category = Literal[
    "Hardware", "Software", "Network",
    "Account", "Printer", "Email", "Other"
]

Priority = Literal["Low", "Medium", "High", "Critical"]


def generate_request_number(cursor) -> str:
    """
    สร้างเลขที่คำร้องอัตโนมัติในฝั่ง Backend (เช่น IS2610016)
    รูปแบบ: IS + YY (ปี 2 หลัก) + MM (เดือน 2 หลัก) + ลำดับ 3 หลัก (001, 002, ...)
    รันลำดับต่อเนื่องในแต่ละเดือน และรีเซ็ตอัตโนมัติเมื่อขึ้นเดือนใหม่
    """
    now = datetime.now()
    prefix = f"IS{now.strftime('%y%m')}"

    cursor.execute("""
        SELECT request_number
        FROM tickets
        WHERE request_number LIKE %s
        ORDER BY LENGTH(request_number) DESC, request_number DESC
        LIMIT 1
        FOR UPDATE;
    """, (f"{prefix}%",))

    row = cursor.fetchone()
    if row and row.get("request_number"):
        last_num = str(row["request_number"]).strip()
        seq_str = last_num[len(prefix):]
        try:
            seq = int(seq_str) + 1
        except ValueError:
            seq = 1
    else:
        seq = 1

    return f"{prefix}{seq:03d}"


def get_or_create_other_user(
    cursor,
    requester_name: str,
    department: str | None,
    requester_id: int | None = None
) -> int:
    """
    ตรวจสอบและดึง ID ของผู้ใช้งานจากตาราง other_user
    1. หากมี requester_id ส่งมา ให้ตรวจสอบว่ามีอยู่ใน other_user จริงหรือไม่
    2. หากไม่มี ให้ค้นหาจากชื่อ (personal_name หรือ user_name)
    3. หากยังไม่มีในระบบ ให้บันทึกชื่อ (user_name, personal_name) และแผนก (department) ใหม่ลงใน other_user อัตโนมัติ
    """
    clean_name = requester_name.strip()
    clean_dept = department.strip() if department and department.strip() else None

    # 1. กรณีมี requester_id ส่งมาจาก autocomplete
    if requester_id:
        cursor.execute(
            "SELECT id, department FROM other_user WHERE id = %s;",
            (requester_id,)
        )
        row = cursor.fetchone()
        if row:
            if clean_dept and row.get("department") != clean_dept:
                cursor.execute(
                    "UPDATE other_user SET department = %s WHERE id = %s;",
                    (clean_dept, row["id"])
                )
            return row["id"]

    # 2. ค้นหาจากชื่อ เผื่อผู้ใช้พิมพ์ชื่อที่มีในระบบอยู่แล้วแต่ไม่ได้คลิกเลือกจากรายการ
    cursor.execute("""
        SELECT id, department 
        FROM other_user 
        WHERE LOWER(TRIM(personal_name)) = LOWER(%s) 
           OR LOWER(TRIM(user_name)) = LOWER(%s)
        ORDER BY id ASC
        LIMIT 1;
    """, (clean_name, clean_name))
    row = cursor.fetchone()
    if row:
        if clean_dept and row.get("department") != clean_dept:
            cursor.execute(
                "UPDATE other_user SET department = %s WHERE id = %s;",
                (clean_dept, row["id"])
            )
        return row["id"]

    # 3. ไม่พบชื่อใน other_user -> เพิ่มผู้ใช้ใหม่ลงในตาราง other_user
    insert_sql = """
        INSERT INTO other_user (
            user_name,
            personal_name,
            department
        )
        VALUES (%s, %s, %s)
        RETURNING id;
    """
    cursor.execute("SAVEPOINT sp_insert_other_user;")
    try:
        cursor.execute(insert_sql, (clean_name, clean_name, clean_dept))
        new_user = cursor.fetchone()
        cursor.execute("RELEASE SAVEPOINT sp_insert_other_user;")
        logger.info(
            "Inserted new user into other_user: ID=%s, name=%s, dept=%s",
            new_user["id"], clean_name, clean_dept
        )
        return new_user["id"]
    except Exception as e:
        cursor.execute("ROLLBACK TO SAVEPOINT sp_insert_other_user;")
        logger.warning(
            "Insert other_user failed (%s), resyncing sequence and retrying...",
            e
        )
        cursor.execute("""
            SELECT setval(pg_get_serial_sequence('other_user', 'id'), COALESCE(MAX(id), 1))
            FROM other_user;
        """)
        cursor.execute(insert_sql, (clean_name, clean_name, clean_dept))
        new_user = cursor.fetchone()
        logger.info(
            "Inserted new user into other_user after sequence resync: ID=%s, name=%s",
            new_user["id"], clean_name
        )
        return new_user["id"]


@router.post("/tickets")
def create_ticket(
    requester_name: Annotated[str, Form(min_length=1, max_length=150)],
    department: Annotated[str, Form()],
    subject: Annotated[str, Form(min_length=1, max_length=200)],
    category: Annotated[Category, Form()],
    priority: Annotated[Priority, Form()],
    requester_id: Annotated[str | None, Form()] = None,
    contact: Annotated[str, Form(max_length=255)] = "",
    detail: Annotated[str, Form(max_length=10000)] = "",
    asset_tag: Annotated[str, Form(max_length=100)] = "",
    location: Annotated[str, Form(max_length=255)] = "",
):
    requester_name = requester_name.strip()
    subject = subject.strip()

    if not requester_name or not subject:
        raise HTTPException(
            status_code=422,
            detail="กรุณากรอกชื่อผู้แจ้งและหัวข้อปัญหา",
        )

    # รวมรายละเอียดปัญหา หัวข้อ และข้อมูลติดต่อไว้ในช่อง detail เพื่อให้ข้อมูลครบถ้วน
    detail_parts = []
    if subject:
        detail_parts.append(f"หัวข้อ: {subject}")
    if detail.strip():
        detail_parts.append(detail.strip())
    if contact.strip():
        detail_parts.append(f"ช่องทางติดต่อ: {contact.strip()}")
    combined_detail = "\n".join(detail_parts) if detail_parts else None

    # แปลง requester_id หากมีส่งมาจาก autocomplete
    parsed_requester_id = None
    if requester_id and requester_id.strip().isdigit():
        parsed_requester_id = int(requester_id.strip())

    connection = None
    try:
        connection = get_connection()

        with connection.cursor() as cursor:
            # Keep a durable, shared unread marker for newly created tickets.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ticket_notifications (
                    ticket_id INTEGER PRIMARY KEY,
                    is_opened BOOLEAN NOT NULL DEFAULT FALSE
                );
            """)
            # ตรวจสอบหรือสร้างผู้ใช้ใน other_user พร้อมบันทึกชื่อและแผนก
            parsed_requester_id = get_or_create_other_user(
                cursor=cursor,
                requester_name=requester_name,
                department=department,
                requester_id=parsed_requester_id,
            )

            # 1. สร้างเลขที่คำร้องอัตโนมัติในส่วน backend
            auto_request_number = generate_request_number(cursor)

            # 2. บันทึกลงตาราง tickets ตาม schema ของฐานข้อมูลจริง
            sql = """
                INSERT INTO tickets (
                    request_number,
                    requester_id,
                    requester_name,
                    department,
                    error_type,
                    detail,
                    priority,
                    status,
                    asset_tag,
                    location
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING id;
            """
            values = (
                auto_request_number,
                parsed_requester_id,
                requester_name,
                department.strip() or None,
                category,
                combined_detail,
                priority,
                "รอดำเนินการ",
                asset_tag.strip() or None,
                location.strip() or None,
            )

            cursor.execute(sql, values)
            ticket_id = cursor.fetchone()["id"]
            cursor.execute(
                "INSERT INTO ticket_notifications (ticket_id) VALUES (%s);",
                (ticket_id,),
            )

        connection.commit()

        # หลังบันทึกสำเร็จ redirect กลับไปพร้อม created id เพื่อแสดงข้อความแจ้งเตือน
        return RedirectResponse(
            url=f"/it-request?created={ticket_id}",
            status_code=303,
        )

    except Exception:
        if connection is not None:
            connection.rollback()

        logger.exception("Failed to save IT ticket")
        raise HTTPException(
            status_code=500,
            detail="บันทึกคำร้องไม่สำเร็จ กรุณาลองใหม่อีกครั้ง",
        )

    finally:
        if connection is not None:
            connection.close()


# -----------------------------------------------------------------------
# Asset Management Routes
# -----------------------------------------------------------------------

def _ensure_sequences(cursor) -> None:
    """ซิงค์ sequence ทุกตาราง asset ป้องกัน identity column ชนกับข้อมูลเก่า"""
    for table, seq in [
        ("it_asset",        "pc_complete_id_seq"),
        ("pc_component",    "pc_component_id_seq"),
        ("asset_assembly",  "asset_assembly_id_seq"),
        ("pc_software",     "pc_software_id_seq"),
    ]:
        cursor.execute(
            f"SELECT setval('{seq}', COALESCE(MAX(id), 1)) FROM {table};"
        )


@router.post("/assets/new")
def create_asset(
    service_tag:   Annotated[str, Form(min_length=1, max_length=100)],
    type:          Annotated[str, Form(min_length=1, max_length=100)],
    brand:         Annotated[str, Form(max_length=100)] = "",
    model:         Annotated[str, Form(max_length=200)] = "",
    machine_name:  Annotated[str, Form(max_length=200)] = "",
    price:         Annotated[str, Form()] = "0",
    buy_date:      Annotated[str, Form()] = "",
    supplier:      Annotated[str, Form(max_length=200)] = "",
    warranty_year: Annotated[str, Form()] = "",
    warranty_exp:  Annotated[str, Form()] = "",
    remark:        Annotated[str, Form(max_length=2000)] = "",
):
    service_tag = service_tag.strip().upper()

    price_val = 0.0
    try:
        if price.strip():
            price_val = float(price.strip())
    except ValueError:
        price_val = 0.0

    buy_date_val = None
    try:
        if buy_date.strip():
            buy_date_val = date.fromisoformat(buy_date.strip())
    except ValueError:
        pass

    warranty_year_val = None
    try:
        if warranty_year.strip():
            warranty_year_val = float(warranty_year.strip())
    except ValueError:
        pass

    warranty_exp_val = None
    try:
        if warranty_exp.strip():
            warranty_exp_val = date.fromisoformat(warranty_exp.strip())
    except ValueError:
        pass

    connection = None
    try:
        connection = get_connection()
        with connection.cursor() as cur:
            # ซิงค์ sequence ก่อนทุกครั้ง
            _ensure_sequences(cur)

            # ตรวจซ้ำ service_tag
            cur.execute(
                "SELECT id FROM it_asset WHERE service_tag = %s;",
                (service_tag,)
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=422,
                    detail=f"Service Tag '{service_tag}' มีในระบบอยู่แล้ว กรุณาใช้รหัสอื่น"
                )

            cur.execute("""
                INSERT INTO it_asset (
                    service_tag, type, brand, "Model", machine_name,
                    price, buy_date, supplier, warranty_year, warranty_exp, remark
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                service_tag,
                type.strip(),
                brand.strip() or None,
                model.strip() or None,
                machine_name.strip() or None,
                price_val,
                buy_date_val,
                supplier.strip() or None,
                warranty_year_val,
                warranty_exp_val,
                remark.strip() or None,
            ))
            new_id = cur.fetchone()["id"]
            logger.info("Created new asset ID=%s service_tag=%s", new_id, service_tag)

        connection.commit()
        return RedirectResponse(url="/assets?created=asset", status_code=303)

    except HTTPException:
        if connection:
            connection.rollback()
        raise
    except Exception:
        if connection:
            connection.rollback()
        logger.exception("Failed to create asset")
        raise HTTPException(status_code=500, detail="บันทึกข้อมูลอุปกรณ์ไม่สำเร็จ กรุณาลองใหม่")
    finally:
        if connection:
            connection.close()


@router.post("/assets/component/new")
def create_component(
    item_name:      Annotated[str, Form(min_length=1, max_length=300)],
    type:           Annotated[str, Form(min_length=1, max_length=100)],
    brand:          Annotated[str, Form(max_length=100)] = "",
    serialnumber:   Annotated[str, Form(max_length=200)] = "",
    detail_spac:    Annotated[str, Form(max_length=500)] = "",
    price:          Annotated[str, Form()] = "0",
    buy_date:       Annotated[str, Form()] = "",
    supplier:       Annotated[str, Form(max_length=200)] = "",
    warranty_year:  Annotated[str, Form()] = "",
    warranty_exp:   Annotated[str, Form()] = "",
    attach_to_pc_id: Annotated[str, Form()] = "",
):
    price_val = 0.0
    try:
        if price.strip():
            price_val = float(price.strip())
    except ValueError:
        pass

    buy_date_val = None
    try:
        if buy_date.strip():
            buy_date_val = date.fromisoformat(buy_date.strip())
    except ValueError:
        pass

    warranty_year_val = None
    try:
        if warranty_year.strip():
            warranty_year_val = float(warranty_year.strip())
    except ValueError:
        pass

    warranty_exp_val = None
    try:
        if warranty_exp.strip():
            warranty_exp_val = date.fromisoformat(warranty_exp.strip())
    except ValueError:
        pass

    pc_id = None
    if attach_to_pc_id.strip().isdigit():
        pc_id = int(attach_to_pc_id.strip())

    sn = serialnumber.strip() or None

    connection = None
    try:
        connection = get_connection()
        with connection.cursor() as cur:
            _ensure_sequences(cur)

            # ตรวจ duplicate serial number
            if sn:
                cur.execute(
                    "SELECT id FROM pc_component WHERE serialnumber = %s;", (sn,)
                )
                if cur.fetchone():
                    raise HTTPException(
                        status_code=422,
                        detail=f"Serial Number '{sn}' มีในระบบอยู่แล้ว"
                    )

            cur.execute("""
                INSERT INTO pc_component (
                    item_name, type, brand, serialnumber,
                    detail_spac, price, buy_date, supplier,
                    warranty_year, warranty_exp
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                item_name.strip(),
                type.strip(),
                brand.strip() or None,
                sn,
                detail_spac.strip() or None,
                price_val,
                buy_date_val,
                supplier.strip() or None,
                warranty_year_val,
                warranty_exp_val,
            ))
            comp_id = cur.fetchone()["id"]
            logger.info("Created new component ID=%s name=%s", comp_id, item_name)

            # ประกอบเข้าเครื่องทันทีหากเลือก PC
            if pc_id:
                cur.execute("SELECT id FROM it_asset WHERE id = %s;", (pc_id,))
                if cur.fetchone() is None:
                    raise HTTPException(
                        status_code=422,
                        detail=f"ไม่พบอุปกรณ์ ID {pc_id}"
                    )
                _ensure_sequences(cur)
                cur.execute("""
                    INSERT INTO asset_assembly (pc_id, component_id, assembly_date)
                    VALUES (%s, %s, %s);
                """, (pc_id, comp_id, buy_date_val or date.today()))
                logger.info("Auto-assembled component ID=%s to PC ID=%s", comp_id, pc_id)

        connection.commit()
        redirect = f"/assets/assembly?pc_id={pc_id}&success=attach" if pc_id else "/assets?created=component"
        return RedirectResponse(url=redirect, status_code=303)

    except HTTPException:
        if connection:
            connection.rollback()
        raise
    except Exception:
        if connection:
            connection.rollback()
        logger.exception("Failed to create component")
        raise HTTPException(status_code=500, detail="บันทึกชิ้นส่วนไม่สำเร็จ กรุณาลองใหม่")
    finally:
        if connection:
            connection.close()


@router.post("/assets/assembly/attach")
def attach_component(
    pc_id:        Annotated[int, Form()],
    component_id: Annotated[int, Form()],
    assembly_date: Annotated[str, Form()] = "",
):
    assemble_date_val = date.today()
    try:
        if assembly_date.strip():
            assemble_date_val = date.fromisoformat(assembly_date.strip())
    except ValueError:
        pass

    connection = None
    try:
        connection = get_connection()
        with connection.cursor() as cur:
            # ตรวจว่า PC มีอยู่จริง
            cur.execute("SELECT id FROM it_asset WHERE id = %s;", (pc_id,))
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail=f"ไม่พบอุปกรณ์ ID {pc_id}")

            # ตรวจว่า component มีอยู่และยังไม่ได้ประกอบอยู่ในเครื่องใด
            cur.execute("""
                SELECT id FROM asset_assembly
                WHERE component_id = %s AND remove_date IS NULL;
            """, (component_id,))
            if cur.fetchone():
                raise HTTPException(
                    status_code=422,
                    detail="ชิ้นส่วนนี้ประกอบอยู่ในเครื่องอื่นอยู่แล้ว กรุณาถอดออกก่อน"
                )

            _ensure_sequences(cur)
            cur.execute("""
                INSERT INTO asset_assembly (pc_id, component_id, assembly_date)
                VALUES (%s, %s, %s);
            """, (pc_id, component_id, assemble_date_val))
            logger.info("Attached component ID=%s to PC ID=%s", component_id, pc_id)

        connection.commit()
        return RedirectResponse(
            url=f"/assets/assembly?pc_id={pc_id}&success=attach",
            status_code=303
        )

    except HTTPException:
        if connection:
            connection.rollback()
        raise
    except Exception:
        if connection:
            connection.rollback()
        logger.exception("Failed to attach component")
        raise HTTPException(status_code=500, detail="ประกอบชิ้นส่วนไม่สำเร็จ กรุณาลองใหม่")
    finally:
        if connection:
            connection.close()


@router.post("/assets/assembly/detach")
def detach_component(
    assembly_id: Annotated[int, Form()],
    remove_date: Annotated[str, Form()] = "",
):
    remove_date_val = date.today()
    try:
        if remove_date.strip():
            remove_date_val = date.fromisoformat(remove_date.strip())
    except ValueError:
        pass

    connection = None
    try:
        connection = get_connection()
        with connection.cursor() as cur:
            cur.execute(
                "SELECT id, pc_id, remove_date FROM asset_assembly WHERE id = %s;",
                (assembly_id,)
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"ไม่พบบันทึกการประกอบ ID {assembly_id}")
            if row["remove_date"] is not None:
                raise HTTPException(status_code=422, detail="ชิ้นส่วนนี้ถูกถอดออกแล้ว")

            pc_id = row["pc_id"]

            cur.execute("""
                UPDATE asset_assembly
                SET remove_date = %s
                WHERE id = %s;
            """, (remove_date_val, assembly_id))
            logger.info("Detached assembly ID=%s at %s", assembly_id, remove_date_val)

        connection.commit()
        return RedirectResponse(
            url=f"/assets/assembly?pc_id={pc_id}&success=detach",
            status_code=303
        )

    except HTTPException:
        if connection:
            connection.rollback()
        raise
    except Exception:
        if connection:
            connection.rollback()
        logger.exception("Failed to detach component")
        raise HTTPException(status_code=500, detail="ถอดชิ้นส่วนไม่สำเร็จ กรุณาลองใหม่")
    finally:
        if connection:
            connection.close()


@router.post("/ticket/{ticket_id}")
def update_ticket_report(
    ticket_id: int,
    assigned_to: Annotated[str, Form(max_length=150)],
    status: Annotated[str, Form(max_length=50)],
    solution: Annotated[str, Form(max_length=10000)],
    cost_of_repair: Annotated[str, Form()] = "0",
    work_notes: Annotated[str, Form(max_length=10000)] = "",
):
    connection = None
    try:
        connection = get_connection()

        with connection.cursor() as cursor:
            # 1. ตรวจสอบว่ามี Ticket หรือไม่
            cursor.execute("SELECT id FROM tickets WHERE id = %s;", (ticket_id,))
            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"ไม่พบคำร้อง ID {ticket_id}"
                )

            # 2. ค้นหา it_user_id จากชื่อผู้รับผิดชอบ
            assigned_clean = assigned_to.strip()
            cursor.execute("""
                SELECT id FROM it_users
                WHERE user_name ILIKE %s OR personal_name ILIKE %s
                LIMIT 1;
            """, (assigned_clean, assigned_clean))
            user_row = cursor.fetchone()
            it_user_id = user_row["id"] if user_row else None

            # 3. แปลงค่า cost_of_repair ให้เป็นตัวเลข
            cost_val = 0.0
            try:
                if cost_of_repair and cost_of_repair.strip():
                    cost_val = float(cost_of_repair.strip())
            except ValueError:
                cost_val = 0.0

            # 4. ตรวจสอบเวลาเสร็จสิ้น
            completed_at = None
            if status in ["Resolved", "Closed", "แก้ไขแล้ว", "เสร็จสิ้น"]:
                completed_at = datetime.now()

            # 5. อัปเดตสถานะในตาราง tickets
            cursor.execute("""
                UPDATE tickets
                SET status = %s
                WHERE id = %s;
            """, (status, ticket_id))

            # 6. สร้างประวัติการซ่อมเป็นรายการใหม่เสมอ (ไม่ UPDATE ทับของเดิม)
            cursor.execute("""
                INSERT INTO ticket_report (
                    request_id,
                    it_user_id,
                    solution,
                    cost_of_repair,
                    completed_at,
                    remark
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                ticket_id,
                it_user_id,
                solution.strip() or None,
                cost_val,
                completed_at,
                work_notes.strip() or None,
            ))
            new_report_id = cursor.fetchone()["id"]
            logger.info("Created new ticket report record ID %s for ticket ID %s", new_report_id, ticket_id)

        connection.commit()

        return RedirectResponse(
            url=f"/ticket/{ticket_id}?success=true",
            status_code=303,
        )

    except HTTPException:
        raise

    except Exception:
        if connection is not None:
            connection.rollback()

        logger.exception("Failed to update ticket report")
        raise HTTPException(
            status_code=500,
            detail="บันทึกรายงานไม่สำเร็จ กรุณาลองใหม่อีกครั้ง",
        )

    finally:
        if connection is not None:
            connection.close()


# -----------------------------------------------------------------------------------------
# Route สำหรับบันทึกและแก้ไขข้อมูลซอฟต์แวร์ของอุปกรณ์
# -----------------------------------------------------------------------------------------

@router.post("/software/{asset_id}")
def update_software(
    asset_id: int,
    # it_asset data
    machine_name: str | None = Form(default=None),
    # software data
    os: str | None = Form(default=None),
    mac_address: str | None = Form(default=None),
    ipaddress: str | None = Form(default=None),
    rc_program: str | None = Form(default=None),
    rc_id: str | None = Form(default=None),
    rc_password: str | None = Form(default=None),
    email: str | None = Form(default=None),
    email_password: str | None = Form(default=None),
    other_software: str | None = Form(default=None),
):
    connection = None

    try:
        connection = get_connection()

        with connection.cursor() as cur:
            _ensure_sequences(cur)

            # ตรวจสอบว่ามีอุปกรณ์อยู่จริง
            cur.execute("SELECT id FROM it_asset WHERE id = %s;", (asset_id,))
            if cur.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"ไม่พบอุปกรณ์ ID {asset_id}"
                )

            # อัปเดต machine_name ใน it_asset หากมีการกรอก
            if machine_name is not None:
                cur.execute("""
                    UPDATE it_asset
                    SET machine_name = %s
                    WHERE id = %s;
                """, (machine_name.strip() or None, asset_id))

            # ทำความสะอาดข้อมูล
            clean_os = os.strip() if os and os.strip() else None
            clean_mac = mac_address.strip() if mac_address and mac_address.strip() else None
            clean_ip = ipaddress.strip() if ipaddress and ipaddress.strip() else None
            clean_rc_program = rc_program.strip() if rc_program and rc_program.strip() else None
            clean_rc_id = rc_id.strip() if rc_id and rc_id.strip() else None
            clean_rc_password = rc_password.strip() if rc_password and rc_password.strip() else None
            clean_email = email.strip() if email and email.strip() else None
            clean_email_pwd = email_password.strip() if email_password and email_password.strip() else None
            clean_other = other_software.strip() if other_software and other_software.strip() else None

            # บันทึกหรืออัปเดตข้อมูล pc_software
            cur.execute("""
                INSERT INTO pc_software (
                    asset_id,
                    os,
                    mac_address,
                    ipaddress,
                    rc_program,
                    rc_id,
                    rc_password,
                    email,
                    email_password,
                    other_software
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
                ON CONFLICT (asset_id)
                DO UPDATE SET
                    os = excluded.os,
                    mac_address = excluded.mac_address,
                    ipaddress = excluded.ipaddress,
                    rc_program = excluded.rc_program,
                    rc_id = excluded.rc_id,
                    rc_password = excluded.rc_password,
                    email = excluded.email,
                    email_password = excluded.email_password,
                    other_software = excluded.other_software;
            """, (
                asset_id,
                clean_os,
                clean_mac,
                clean_ip,
                clean_rc_program,
                clean_rc_id,
                clean_rc_password,
                clean_email,
                clean_email_pwd,
                clean_other,
            ))

        connection.commit()

        return RedirectResponse(
            url=f"/software/{asset_id}?success=true",
            status_code=303,
        )

    except HTTPException:
        if connection is not None:
            connection.rollback()
        raise
    except Exception:
        if connection is not None:
            connection.rollback()
        logger.exception("Failed to update software data")
        raise HTTPException(
            status_code=500,
            detail="บันทึกข้อมูลซอฟต์แวร์ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"
        )
    finally:
        if connection is not None:
            connection.close()
