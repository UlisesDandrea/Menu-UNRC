import asyncio
import os
import json
import time
from datetime import datetime
from playwright.async_api import async_playwright

DNI       = os.environ.get("UNRC_DNI",      "")
PASSWORD  = os.environ.get("UNRC_PASSWORD", "")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

async def verificar_reintento(page):
    intentos = 0
    while True:
        boton_reintentar = await page.query_selector("#volver")
        if boton_reintentar:
            intentos += 1
            print(f"⚠️ Límite de conexiones (intento {intentos}). Reintentando...")
            await boton_reintentar.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(3)
        else:
            if intentos > 0:
                print(f"✅ Error resuelto después de {intentos} intento(s)")
            return intentos > 0

async def intentar_compra(page, fecha_hoy):
    await page.goto("https://sisinfo.unrc.edu.ar/gisau/compra_menu.php", wait_until="networkidle")
    await verificar_reintento(page)
    await page.screenshot(path=f"menu_{fecha_hoy}.png", full_page=True)

    turnos = await page.query_selector_all("input[name='turno']")
    if not turnos:
        print("⚠️ Sin turnos disponibles")
        return False

    print(f"🕐 {len(turnos)} turno(s) encontrados")

    for i, turno in enumerate(turnos):
        turno_valor = await turno.get_attribute("value")
        print(f"🛒 Probando turno {i+1} (valor: {turno_valor})...")

        cupo_elem = await page.query_selector(f"#cupo{i+1}")
        if cupo_elem:
            cupo_texto = await cupo_elem.inner_text()
            if "0 disponibles" in cupo_texto:
                print(f"❌ Turno {i+1} sin cupos, probando siguiente...")
                continue

        await page.evaluate(f"""
            () => {{
                const radios = document.getElementsByName('turno');
                if (radios[{i}]) radios[{i}].checked = true;
                if (document.compra) document.compra.turnosel.value = '{turno_valor}';
            }}
        """)
        await asyncio.sleep(1)

        boton = await page.query_selector("#botcompra")
        if not boton:
            boton = await page.query_selector("button.btn-success, button:has-text('Comprar')")

        if boton:
            await boton.click(force=True)
        else:
            print("⚠️ No se encontró el botón de compra")
            continue

        await asyncio.sleep(4)
        await verificar_reintento(page)

        area = await page.query_selector("#area_mensaje")
        if area:
            texto = await area.inner_text()
            if "EXITOSAMENTE" in texto or "ÉXITO" in texto:
                print(f"✅ ¡Compra exitosa en turno {i+1}!")
                await page.screenshot(path=f"menu_{fecha_hoy}.png", full_page=True)
                return True
            elif "ya comprado" in texto.lower():
                print("ℹ️ El menú ya estaba comprado")
                return True
            else:
                print(f"⚠️ Turno {i+1} falló: {texto[:80]}")
                await page.goto("https://sisinfo.unrc.edu.ar/gisau/compra_menu.php", wait_until="networkidle")
                await verificar_reintento(page)
                turnos = await page.query_selector_all("input[name='turno']")

    return False


async def obtener_menu():
    ESPERA_ENTRE_INTENTOS = 15  # segundos entre intentos
    TIEMPO_LIMITE = 30 * 60     # 30 minutos en segundos
    inicio = time.time()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page    = await context.new_page()

        # ── Login UNA SOLA VEZ ────────────────────────────────────────────
        print("🌐 Abriendo página...")
        await page.goto("https://sisinfo.unrc.edu.ar/gisau/compra_menu.php", wait_until="networkidle")
        await verificar_reintento(page)

        print("🔐 Completando login...")
        try:
            await page.wait_for_selector("#nrodoc", timeout=15000)
            await page.fill("#nrodoc", DNI)
            await page.fill("#clave", PASSWORD)
            await page.click("button:has-text('Ingresar')")
            await page.wait_for_load_state("networkidle")
            await verificar_reintento(page)
            print("✅ Login OK")
        except Exception as e:
            print(f"❌ Error en login: {e}")
            await browser.close()
            return {"comprado": False}

        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        comprado = False
        intento = 0

        # ── Intentar durante 30 minutos ───────────────────────────────────
        while True:
            tiempo_transcurrido = time.time() - inicio
            if tiempo_transcurrido >= TIEMPO_LIMITE:
                print(f"\n⏰ Se agotaron los 30 minutos. Terminando.")
                break

            intento += 1
            minutos_restantes = int((TIEMPO_LIMITE - tiempo_transcurrido) / 60)
            print(f"\n{'='*40}")
            print(f"🔄 INTENTO {intento} — {minutos_restantes} min restantes")
            print(f"{'='*40}")

            try:
                comprado = await intentar_compra(page, fecha_hoy)
                if comprado:
                    print(f"\n🎉 ¡Comprado en el intento {intento}!")
                    break
            except Exception as e:
                print(f"❌ Error: {e}")

            # Verificar tiempo antes de esperar
            if time.time() - inicio + ESPERA_ENTRE_INTENTOS < TIEMPO_LIMITE:
                print(f"⏳ Esperando {ESPERA_ENTRE_INTENTOS}s...")
                await asyncio.sleep(ESPERA_ENTRE_INTENTOS)

        # Screenshot final
        await page.screenshot(path=f"menu_{fecha_hoy}.png", full_page=True)
        print("📸 Screenshot final guardado")

        datos_menu = {
            "fecha":     fecha_hoy,
            "texto":     "compra automatica",
            "comprado":  str(comprado),
            "timestamp": datetime.now().isoformat()
        }

        with open(f"menu_{fecha_hoy}.json", "w", encoding="utf-8") as f:
            json.dump(datos_menu, f, ensure_ascii=False, indent=2)
        print(f"💾 comprado={comprado}")

        if SUPABASE_URL and SUPABASE_KEY:
            await guardar_en_supabase(datos_menu)

        await browser.close()
        return datos_menu


async def guardar_en_supabase(datos):
    try:
        import httpx
        headers = {
            "apikey":        SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type":  "application/json",
            "Prefer":        "resolution=merge-duplicates"
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{SUPABASE_URL}/rest/v1/menus",
                headers=headers,
                json=datos
            )
            if resp.status_code in (200, 201):
                print("☁️ Guardado en Supabase")
            else:
                print(f"⚠️ Error Supabase: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"⚠️ No se pudo guardar: {e}")


if __name__ == "__main__":
    asyncio.run(obtener_menu())
