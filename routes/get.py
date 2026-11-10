import logging
import math
import urllib.parse
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from psycopg.pq import error_message

from database import get_connection

logger = logging.getLogger(__name__)
router = APIRouter()

# ตั้งค่าตำแหน่งโฟลเดอร์ template
templates = Jinja2Templates(directory="template")


def get_pagination_pages(current_page: int, total_pages: int) -> list:
    """Return a list of page numbers and ellipsis, e.g. [1, 2, 3, '...', 10]."""
    if total_pages <= 7:
        return list(range(1, total_pages + 1))

    pages: list = [1]
    start = max(2, current_page - 2)
    end = min(total_pages - 1, current_page + 2)

    if start > 2:
        pages.append("...")
    for p in range(start, end + 1):
        pages.append(p)
    if end < total_pages - 1:
        pages.append("...")

    pages.append(total_pages)
    return pages



@router.get("/api/notifications")
def get_ticket_notifications():
    """Return tickets that have not yet been opened, for the global bell."""
    connection = None
    try:
        connection = get_connection()
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ticket_notifications (
                    ticket_id INTEGER PRIMARY KEY,
                    is_opened BOOLEAN NOT NULL DEFAULT FALSE
                );
            """)
            cursor.execute("""
                SELECT t.id, t.request_number, t.error_type, t.request_at
                FROM tickets t
                JOIN ticket_notifications tn ON tn.ticket_id = t.id
                WHERE tn.is_opened = FALSE
                ORDER BY t.id DESC
                LIMIT 50;
            """)
            rows = cursor.fetchall()
        connection.commit()
        return {
            "count": len(rows),
            "tickets": [
                {
                    "id": row["id"],
                    "request_number": row["request_number"],
                    "subject": row["error_type"],
                }
                for row in rows
            ],
        }
    except Exception:
        logger.exception("Failed to fetch ticket notifications")
        raise HTTPException(status_code=500, detail="Unable to fetch notifications")
    finally:
        if connection is not None:
            connection.close()


# 1. Route หน้าหลัก (Home) ---------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
@router.get("/home", response_class=HTMLResponse)
async def read_home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={}
    )


# 2. Route หน้าแจ้งปัญหา IT (IT Request) -------------------------------------------
@router.get("/it-request", response_class=HTMLResponse)
async def read_it_request(request: Request, created: int | None = None):
    success_message = None

    if created:
        connection = None
        try:
            connection = get_connection()
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT request_number FROM tickets WHERE id = %s;",
                    (created,)
                )
                ticket_row = cursor.fetchone()
                if ticket_row and ticket_row.get("request_number"):
                    success_message = f"บันทึกคำร้องสำเร็จ! หมายเลขคำร้องของคุณคือ: {ticket_row['request_number']}"
                else:
                    success_message = "บันทึกคำร้องสำเร็จเรียบร้อยแล้ว"
        except Exception:
            logger.exception("Failed to query created ticket")
            success_message = "บันทึกคำร้องสำเร็จเรียบร้อยแล้ว"
        finally:
            if connection is not None:
                connection.close()

    return templates.TemplateResponse(
        request=request,
        name="it_request.html",
        context={"success_message": success_message}
    )


# 3. Route หน้าแสดงรายการคำร้องของผู้ใช้งาน (My Tickets) ------------------------------
@router.get("/my-tickets", response_class=HTMLResponse)
async def read_my_tickets(
    request: Request,
    page: int = Query(default=1, ge=1),
):
    connection = None
    tickets = []
    per_page = 20
    total_count = 0
    total_pages = 1

    try:
        connection = get_connection()
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ticket_notifications (
                    ticket_id INTEGER PRIMARY KEY,
                    is_opened BOOLEAN NOT NULL DEFAULT FALSE
                );
            """)
            cursor.execute("SELECT COUNT(*) AS count FROM tickets;")
            count_row = cursor.fetchone()
            total_count = count_row["count"] if count_row else 0

            total_pages = max(1, math.ceil(total_count / per_page))
            if page > total_pages and total_count > 0:
                page = total_pages
            offset = (page - 1) * per_page

            cursor.execute("""
                SELECT id,
                       request_number,
                       requester_name,
                       error_type,
                       detail,
                       priority,
                       status,
                       request_at,
                       COALESCE(tn.is_opened, TRUE) AS is_opened
                FROM tickets t
                LEFT JOIN ticket_notifications tn ON tn.ticket_id = t.id
                ORDER BY t.id DESC
                LIMIT %s OFFSET %s;
            """, (per_page, offset))
            tickets = cursor.fetchall()
        connection.commit()
    except Exception:
        logger.exception("Failed to fetch tickets")
    finally:
        if connection is not None:
            connection.close()

    start_idx = (page - 1) * per_page + 1 if total_count > 0 else 0
    end_idx = min(page * per_page, total_count)
    page_numbers = get_pagination_pages(page, total_pages)

    return templates.TemplateResponse(
        request=request,
        name="my_tickets.html",
        context={
            "tickets": tickets,
            "page": page,
            "per_page": per_page,
            "total_count": total_count,
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "start_idx": start_idx,
            "end_idx": end_idx,
            "page_numbers": page_numbers,
        }
    )


# 4. Route สำหรับรายงานและจัดการคำร้อง IT (IT Report) -------------------------------
@router.get("/ticket/{ticket_id}", response_class=HTMLResponse)
async def read_it_report(
    request: Request,
    ticket_id: int,
    success: str | None = None,
    error: str | None = None
):
    connection = None

    try:
        connection = get_connection()

        with connection.cursor() as cursor:
            # Opening the ticket detail page clears its new-ticket notice.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ticket_notifications (
                    ticket_id INTEGER PRIMARY KEY,
                    is_opened BOOLEAN NOT NULL DEFAULT FALSE
                );
            """)
            cursor.execute(
                "UPDATE ticket_notifications SET is_opened = TRUE WHERE ticket_id = %s;",
                (ticket_id,),
            )
            # ดึงข้อมูล Ticket ครบทุก field ที่ต้องนำไปแสดงใน template
            cursor.execute("""
                SELECT
                    id,
                    request_number,
                    requester_name,
                    requester_id,
                    department,
                    asset_id,
                    asset_tag,
                    location,
                    error_type,
                    detail,
                    priority,
                    status,
                    request_at,
                    remark
                FROM tickets
                WHERE id = %s;
            """, (ticket_id,))

            ticket = cursor.fetchone()

            if ticket is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Ticket ID {ticket_id} not found"
                )

            # ดึงประวัติการดำเนินงานทั้งหมด โดยเรียง id ล่าสุดขึ้นก่อนเสมอ (ORDER BY tr.id DESC)
            cursor.execute("""
                SELECT
                    tr.id,
                    tr.request_id,
                    tr.it_user_id,
                    COALESCE(u.personal_name, u.user_name) as it_user_name,
                    tr.solution,
                    tr.cost_of_repair,
                    tr.completed_at,
                    tr.remark
                FROM ticket_report as tr
                LEFT JOIN it_users AS u
                    ON tr.it_user_id = u.id
                WHERE request_id = %s
                ORDER BY tr.id DESC;
            """, (ticket_id,))

            reports = cursor.fetchall()
            # ดึงตัวล่าสุดเพื่อนำไปแสดงในช่องของฟอร์ม (ตัวแรกใน list เพราะเรียง id DESC)
            report = reports[0] if reports else None

        connection.commit()

        success_msg = "บันทึกรายงานผลการแก้ไขเรียบร้อยแล้ว" if success else None

        return templates.TemplateResponse(
            request=request,
            name="ticket_report.html",
            context={
                "ticket": ticket,
                "report": report,
                "reports": reports,
                "success": success_msg,
                "error": error
            }
        )

    except HTTPException:
        raise

    except Exception:
        logger.exception("Failed to fetch ticket")
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch ticket from database"
        )
    finally:
        if connection is not None:
            connection.close()


# 5. Route สำหรับค้นหาผู้ใช้งาน (Search Users Autocomplete) -------------------------
@router.get("/api/users")
def search_users(q: str = Query(default="", max_length=100)):
    q = q.strip()

    if len(q) < 2:
        return []

    connection = get_connection()

    try:
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    user_name,
                    personal_name,
                    department
                FROM other_user
                WHERE user_name ILIKE %s
                   OR personal_name ILIKE %s
                ORDER BY personal_name
                LIMIT 10;
                """,
                (f"%{q}%", f"%{q}%")
            )

            rows = cur.fetchall()

        return [
            {
                "id": row["id"],
                "user_name": row["user_name"],
                "personal_name": row["personal_name"],
                "department": row["department"]
            }
            for row in rows
        ]
    finally:
        connection.close()


# 6. Route หน้าทะเบียนทรัพย์สิน IT (Asset List) ----------------------------------------
@router.get("/assets", response_class=HTMLResponse)
async def read_assets(
    request: Request,
    q: str = Query(default="", max_length=200),
    type: str = Query(default="", max_length=100),
    brand: str = Query(default="", max_length=100),
    created: str | None = None,
    page: int = Query(default=1, ge=1),
):
    success_message = None
    if created == "asset":
        success_message = "บันทึกข้อมูลอุปกรณ์ใหม่เรียบร้อยแล้ว"
    elif created == "component":
        success_message = "บันทึกชิ้นส่วนคอมพิวเตอร์เรียบร้อยแล้ว"

    connection = None
    per_page = 20
    total_count = 0
    total_pages = 1
    assets = []
    types = []
    brands = []
    stats = {}

    try:
        connection = get_connection()
        with connection.cursor() as cur:
            # ดึงรายการทรัพย์สินพร้อม Filter
            filters = []
            params: list = []

            if q.strip():
                filters.append(
                    "(a.service_tag ILIKE %s OR a.brand ILIKE %s OR a.\"Model\" ILIKE %s OR a.machine_name ILIKE %s)"
                )
                like = f"%{q.strip()}%"
                params += [like, like, like, like]
            if type.strip():
                filters.append("a.type = %s")
                params.append(type.strip())
            if brand.strip():
                filters.append("a.brand = %s")
                params.append(brand.strip())

            where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

            # นับจำนวนรายการทั้งหมดที่ตรงกับ filter
            cur.execute(f"SELECT COUNT(*) AS count FROM it_asset a {where_clause};", params)
            count_row = cur.fetchone()
            total_count = count_row["count"] if count_row else 0

            total_pages = max(1, math.ceil(total_count / per_page))
            if page > total_pages and total_count > 0:
                page = total_pages
            offset = (page - 1) * per_page

            cur.execute(f"""
                SELECT
                    a.id,
                    a.service_tag,
                    a.type,
                    a.brand,
                    a."Model"      AS model,
                    a.machine_name,
                    a.price,
                    a.buy_date,
                    a.warranty_exp,
                    COALESCE(
                        (SELECT COUNT(*) FROM asset_assembly aa
                         WHERE aa.pc_id = a.id AND aa.remove_date IS NULL),
                        0
                    ) AS active_components_count
                FROM it_asset a
                {where_clause}
                ORDER BY a.id ASC
                LIMIT %s OFFSET %s;
            """, list(params) + [per_page, offset])
            assets = cur.fetchall()

            # ดึงรายการประเภทและยี่ห้อสำหรับ Filter
            cur.execute("SELECT DISTINCT type FROM it_asset WHERE type IS NOT NULL ORDER BY type;")
            types = [r["type"] for r in cur.fetchall()]

            cur.execute("SELECT DISTINCT brand FROM it_asset WHERE brand IS NOT NULL ORDER BY brand;")
            brands = [r["brand"] for r in cur.fetchall()]

            # สถิติภาพรวม
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE type LIKE '%คอม%') AS pc_count,
                    COUNT(*) FILTER (WHERE type LIKE '%พิมพ์%') AS printer_count,
                    COUNT(*) FILTER (WHERE type NOT LIKE '%คอม%' AND type NOT LIKE '%พิมพ์%') AS other_count,
                    COUNT(*) AS total_count
                FROM it_asset;
            """)
            stats = cur.fetchone()

        filter_params = {k: v for k, v in [("q", q.strip()), ("type", type.strip()), ("brand", brand.strip())] if v}
        extra_query = urllib.parse.urlencode(filter_params)
        query_string = f"&{extra_query}" if extra_query else ""

        start_idx = (page - 1) * per_page + 1 if total_count > 0 else 0
        end_idx = min(page * per_page, total_count)
        page_numbers = get_pagination_pages(page, total_pages)

        return templates.TemplateResponse(
            request=request,
            name="assets.html",
            context={
                "assets": assets,
                "types": types,
                "brands": brands,
                "stats": stats,
                "q": q,
                "selected_type": type,
                "selected_brand": brand,
                "today": date.today(),
                "success_message": success_message,
                "page": page,
                "per_page": per_page,
                "total_count": total_count,
                "total_pages": total_pages,
                "has_prev": page > 1,
                "has_next": page < total_pages,
                "start_idx": start_idx,
                "end_idx": end_idx,
                "page_numbers": page_numbers,
                "query_string": query_string,
            }
        )

    except Exception:
        logger.exception("Failed to fetch assets")
        raise HTTPException(status_code=500, detail="ไม่สามารถโหลดข้อมูลทรัพย์สินได้")
    finally:
        if connection is not None:
            connection.close()


# 7. Route หน้าบันทึกอุปกรณ์ใหม่ (New Asset Registration) ---------------------------------
@router.get("/assets/new", response_class=HTMLResponse)
async def read_asset_new(
    request: Request,
    tab: str = Query(default="asset"),
):
    connection = None
    try:
        connection = get_connection()
        with connection.cursor() as cur:
            # รายชื่อ PC/เครื่องทั้งหมดสำหรับ dropdown เลือก PC ตอนเพิ่มชิ้นส่วน
            cur.execute("""
                SELECT id, service_tag, brand, "Model" AS model, machine_name
                FROM it_asset
                WHERE type LIKE '%คอม%'
                ORDER BY service_tag;
            """)
            pcs = cur.fetchall()

        return templates.TemplateResponse(
            request=request,
            name="asset_new.html",
            context={
                "pcs": pcs,
                "active_tab": tab,
                "today_str": date.today().isoformat(),
                "success_message": None,
                "error_message": None,
            }
        )
    except Exception:
        logger.exception("Failed to load asset new page")
        raise HTTPException(status_code=500, detail="ไม่สามารถโหลดหน้าบันทึกอุปกรณ์ได้")
    finally:
        if connection is not None:
            connection.close()


# 8. Route หน้าการถอด-ประกอบชิ้นส่วน (Assembly Management) --------------------------------
@router.get("/assets/assembly", response_class=HTMLResponse)
async def read_asset_assembly(
    request: Request,
    pc_id: int | None = None,
    success: str | None = None,
    error: str | None = None,
):
    connection = None
    try:
        connection = get_connection()
        with connection.cursor() as cur:
            # ดึงรายการ asset ทั้งหมดสำหรับ dropdown
            cur.execute("""
                SELECT id, service_tag, brand, "Model" AS model, machine_name, type
                FROM it_asset
                ORDER BY service_tag;
            """)
            pc_list = cur.fetchall()

            # ถ้ายังไม่ได้เลือกเครื่อง ใช้ตัวแรก
            if pc_id is None and pc_list:
                pc_id = pc_list[0]["id"]

            selected_pc = None
            active_components = []
            history_components = []
            available_components = []

            if pc_id:
                # ข้อมูลเครื่องที่เลือก
                cur.execute("""
                    SELECT id, service_tag, type, brand, "Model" AS model, machine_name, price, buy_date
                    FROM it_asset
                    WHERE id = %s;
                """, (pc_id,))
                selected_pc = cur.fetchone()

                if selected_pc is None:
                    raise HTTPException(status_code=404, detail=f"ไม่พบอุปกรณ์ ID {pc_id}")

                # ชิ้นส่วนที่ประกอบอยู่ปัจจุบัน (remove_date IS NULL)
                cur.execute("""
                    SELECT
                        aa.id AS assembly_id,
                        c.id AS component_id,
                        c.type AS component_type,
                        c.item_name,
                        c.brand,
                        c.serialnumber,
                        c.detail_spac,
                        aa.assembly_date
                    FROM asset_assembly aa
                    JOIN pc_component c ON c.id = aa.component_id
                    WHERE aa.pc_id = %s AND aa.remove_date IS NULL
                    ORDER BY c.type, c.item_name;
                """, (pc_id,))
                active_components = cur.fetchall()

                # ประวัติชิ้นส่วนที่ถอดออกแล้ว (remove_date IS NOT NULL)
                cur.execute("""
                    SELECT
                        c.type AS component_type,
                        c.item_name,
                        c.brand,
                        c.serialnumber,
                        aa.assembly_date,
                        aa.remove_date
                    FROM asset_assembly aa
                    JOIN pc_component c ON c.id = aa.component_id
                    WHERE aa.pc_id = %s AND aa.remove_date IS NOT NULL
                    ORDER BY aa.remove_date DESC;
                """, (pc_id,))
                history_components = cur.fetchall()

                # ชิ้นส่วนที่ว่างอยู่ (ยังไม่ได้ประกอบเข้าเครื่องใด หรือถอดออกมาแล้ว)
                cur.execute("""
                    SELECT id, type, item_name, brand, serialnumber, detail_spac
                    FROM pc_component
                    WHERE id NOT IN (
                        SELECT component_id
                        FROM asset_assembly
                        WHERE remove_date IS NULL
                    )
                    ORDER BY type, item_name;
                """)
                available_components = cur.fetchall()

        success_message = None
        error_message = None
        if success == "attach":
            success_message = "ประกอบชิ้นส่วนเข้าเครื่องเรียบร้อยแล้ว"
        elif success == "detach":
            success_message = "ถอดชิ้นส่วนออกจากเครื่องเรียบร้อยแล้ว"
        if error:
            error_message = error

        return templates.TemplateResponse(
            request=request,
            name="asset_assembly.html",
            context={
                "pc_list": pc_list,
                "selected_pc": selected_pc,
                "active_components": active_components,
                "history_components": history_components,
                "available_components": available_components,
                "today_str": date.today().isoformat(),
                "success_message": success_message,
                "error_message": error_message,
            }
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to load assembly page")
        raise HTTPException(status_code=500, detail="ไม่สามารถโหลดหน้าจัดการชิ้นส่วนได้")
    finally:
        if connection is not None:
            connection.close()

#route สำหรับแสดงข้อมูล software ---------------------------------------------------------------------

@router.get("/software/{asset_id}", response_class=HTMLResponse)
async def read_software(
    request: Request,
    asset_id: int,
    success: str | None = None,
    error: str | None = None,
):

    connection = None

    try:
        connection = get_connection()

        with connection.cursor() as cur:
            # ดึงตัว asset ที่เลือกมาแสดงรายละเอียด
            cur.execute("""
                SELECT
                    id,
                    service_tag,
                    type,
                    brand,
                    machine_name
                from it_asset
                WHERE id = %s
            """, (asset_id,))
            asset = cur.fetchone()

            if asset is None:
                raise HTTPException(
                    status_code=404, 
                    detail=f"ไม่พบอุปกรณ์ ID {asset_id}"
                    )

            # ดึงรายการ software ของ asset ที่เลือก พร้อม filter
            cur.execute("""
                SELECT
                    id,
                    os,
                    mac_address,
                    ipaddress,
                    rc_program,
                    rc_id,
                    rc_password,
                    asset_id,
                    email,
                    email_password,
                    other_software
                FROM pc_software
                WHERE asset_id = %s;
            """, (asset_id,))

            softwares = cur.fetchone()

            success_message = "บันทึกเรียบร้อยแล้ว" if success else None
            

            return templates.TemplateResponse(
                request=request,
                name="asset_software.html",
                context={
                    "asset": asset,
                    "softwares": softwares,
                    "success_message": success_message,
                    "error": error
                }
            )
    except HTTPException:
        raise HTTPException(
            status_code=500, 
            detail=f"ไม่พบอุปกรณ์ ID {asset_id}"
            )
    finally:
        if connection is not None:
            connection.close()
