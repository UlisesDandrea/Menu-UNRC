import asyncio
import os
import json
import time
from datetime import datetime
from playwright.async_api import async_playwright

DNI       = os.environ.get("UNRC_DNI",      "")
PASSWORD  = os.environ.get("UNRC_PASSWORD", "")
URL_LOGIN = "https://sisinfo.unrc.edu.ar/gisau/compra_menu.php"

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

async def obtener_menu():
    MAX_INTENTOS = 35
    ESPERA = 15

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page    = await context.new_page()

        # ── 1. Login UNA SOLA VEZ ─────────────────────────────────────────
        print("🌐 Abriendo página...")
        await page.goto(URL_LOGIN, wait_until="networkidle")
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
            return {"comprado": False, "turno_comprado": None}

        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        comprado = False
        turno_comprado = None

        # ── 2. Intentar comprar (5 intentos, misma sesión) ────────────────
        for intento in range(1, MAX_INTENTOS + 1):
            print(f"\n{'='*40}")
            print(f"🔄 INTENTO {intento} de {MAX_INTENTOS}")
            print(f"{'='*40}")

            # Recargar la página de compra
            await page.goto("https://sisinfo.unrc.edu.ar/gisau/compra_menu.php", wait_until="networkidle")
            await verificar_reintento(page)

            # Screenshot del estado actual
            await page.screenshot(path=f"menu_{fecha_hoy}.png", full_page=True)

            # Buscar turnos
            turnos = await page.query_selector_all("input[name='turno']")
            if not turnos:
                print("⚠️ Sin turnos disponibles en este intento")
                if intento < MAX_INTENTOS:
                    print(f"⏳ Esperando {ESPERA}s...")
                    await asyncio.sleep(ESPERA)
                continue

            print(f"🕐 Se encontraron {len(turnos)} turno(s)")

            for i, turno in enumerate(turnos):
                turno_valor = await turno.get_attribute("value")
                print(f"🛒 Probando turno {i+1} (valor: {turno_valor})...")

                # Verificar cupos
                cupo_elem = await page.query_selector(f"#cupo{i+1}")
                if cupo_elem:
                    cupo_texto = await cupo_elem.inner_text()
                    if "0 disponibles" in cupo_texto:
                        print(f"❌ Turno {i+1} sin cupos")
                        continue

                # Seleccionar turno y clickear via JavaScript (evita el problema de disabled)
                await page.evaluate(f"""
                    () => {{
                        const radios = document.getElementsByName('turno');
                        if (radios[{i}]) radios[{i}].checked = true;
                        document.compra.turnosel.value = '{turno_valor}';
                    }}
                """)
                await asyncio.sleep(1)

                # Click en el botón via JavaScript para evitar el error de disabled
                await page.evaluate("""
                    () => {
                        const btn = document.querySelector('input[type="submit"]');
                        if (btn) btn.removeAttribute('disabled');
                    }
                """)

                boton = await page.query_selector("input[type='submit']")
                if boton:
                    await boton.click(force=True)
                else:
                    await page.evaluate("document.querySelector('input[type=\"submit\"]').click()")

                await asyncio.sleep(4)
                await verificar_reintento(page)

                area = await page.query_selector("#area_mensaje")
                if area:
                    texto = await area.inner_text()
                    if "EXITOSAMENTE" in texto or "ÉXITO" in texto:
                        print(f"✅ ¡Compra exitosa en turno {i+1}!")
                        comprado = True
                        turno_comprado = turno_valor
                        break
                    elif "ya comprado" in texto.lower():
                        print("ℹ️ El menú ya estaba comprado")
                        comprado = True
                        break
                    else:
                        print(f"⚠️ Turno {i+1}: {texto[:80]}")

            if comprado:
                break

            if intento < MAX_INTENTOS:
                print(f"⏳ Esperando {ESPERA}s antes del próximo intento...")
                await asyncio.sleep(ESPERA)

        # Screenshot final
        await page.screenshot(path=f"menu_{fecha_hoy}.png", full_page=True)
        print("📸 Screenshot final guardado")

        datos_menu = {
            "fecha":          fecha_hoy,
            "texto":          "compra automatica",
            "comprado":       str(comprado),
            "turno_comprado": turno_comprado or "",
            "timestamp":      datetime.now().isoformat()
        }

        with open(f"menu_{fecha_hoy}.json", "w", encoding="utf-8") as f:
            json.dump(datos_menu, f, ensure_ascii=False, indent=2)
        print(f"💾 comprado={comprado}, turno={turno_comprado}")

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
