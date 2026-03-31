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
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page    = await context.new_page()

        # ── 1. Login ─────────────────────────────────────────────────────────
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

        # ── 2. Ir al comedor ──────────────────────────────────────────────────
        print("🏫 Navegando al comedor...")
        await page.goto("https://sisinfo.unrc.edu.ar/gisau/index.php", wait_until="networkidle")
        await verificar_reintento(page)

        # ── 3. Entrar a Compra menú diario ────────────────────────────────────
        print("🍽️ Entrando a Compra menú diario...")
        await page.click("a[href='compra_menu.php'], a[title='Compra de menú diario']")
        await page.wait_for_load_state("networkidle")
        await verificar_reintento(page)

        # Screenshot del estado inicial
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        await page.screenshot(path=f"menu_{fecha_hoy}.png", full_page=True)
        print("📸 Screenshot guardado")

        # ── 4. Intentar comprar por cada turno disponible ─────────────────────
        print("🛒 Buscando turnos disponibles...")
        comprado = False
        turno_comprado = None

        try:
            turnos = await page.query_selector_all("input[name='turno']")

            if not turnos:
                print("⚠️ No se encontraron turnos — puede estar fuera de horario o ya comprado")
            else:
                print(f"🕐 Se encontraron {len(turnos)} turno(s)")

                for i, turno in enumerate(turnos):
                    turno_valor = await turno.get_attribute("value")
                    print(f"🔄 Probando turno {i+1} (valor: {turno_valor})...")

                    cupo_id = f"cupo{i+1}"
                    cupo_elem = await page.query_selector(f"#{cupo_id}")
                    if cupo_elem:
                        cupo_texto = await cupo_elem.inner_text()
                        if "0 disponibles" in cupo_texto:
                            print(f"❌ Turno {i+1} sin cupos, probando siguiente...")
                            continue

                    await turno.click()
                    await asyncio.sleep(1)
                    await page.evaluate(f"document.compra.turnosel.value='{turno_valor}'")

                    boton_comprar = await page.query_selector(
                        "input[type='submit'][value*='ompra'], "
                        "input[type='button'][value*='ompra'], "
                        "button:has-text('Comprar'), "
                        "input[type='submit']"
                    )

                    if boton_comprar:
                        await boton_comprar.click()
                    else:
                        await page.evaluate("""
                            () => {
                                const btn = document.querySelector('input[type="submit"]');
                                if (btn) btn.click();
                            }
                        """)

                    await asyncio.sleep(3)
                    await verificar_reintento(page)

                    area_mensaje = await page.query_selector("#area_mensaje")
                    if area_mensaje:
                        mensaje_texto = await area_mensaje.inner_text()
                        if "EXITOSAMENTE" in mensaje_texto or "ÉXITO" in mensaje_texto:
                            print(f"✅ ¡Compra exitosa en turno {i+1}!")
                            comprado = True
                            turno_comprado = turno_valor
                            break
                        elif "ya comprado" in mensaje_texto.lower():
                            print("ℹ️ El menú ya estaba comprado anteriormente")
                            comprado = True
                            break
                        else:
                            print(f"⚠️ Turno {i+1} falló: {mensaje_texto[:100]}")

        except Exception as e:
            print(f"⚠️ Error en el proceso de compra: {e}")

        await page.screenshot(path=f"compra_{fecha_hoy}.png", full_page=True)
        print("📸 Screenshot final guardado")

        datos_menu = {
            "fecha":          fecha_hoy,
            "comprado":       comprado,
            "turno_comprado": turno_comprado,
            "timestamp":      datetime.now().isoformat()
        }

        with open(f"menu_{fecha_hoy}.json", "w", encoding="utf-8") as f:
            json.dump(datos_menu, f, ensure_ascii=False, indent=2)
        print(f"💾 Guardado: comprado={comprado}, turno={turno_comprado}")

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
                print(f"⚠️ Error Supabase: {resp.status_code}")
    except Exception as e:
        print(f"⚠️ No se pudo guardar: {e}")


if __name__ == "__main__":
    MAX_INTENTOS = 30
    ESPERA_ENTRE_INTENTOS = 20  # segundos entre cada intento

    for intento in range(1, MAX_INTENTOS + 1):
        print(f"\n{'='*40}")
        print(f"🔄 INTENTO {intento} de {MAX_INTENTOS}")
        print(f"{'='*40}")
        try:
            resultado = asyncio.run(obtener_menu())
            if resultado.get("comprado"):
                print(f"\n🎉 ¡Menú comprado exitosamente en el intento {intento}!")
                break
            else:
                print(f"\n⏳ Esperando {ESPERA_ENTRE_INTENTOS}s antes del próximo intento...")
                time.sleep(ESPERA_ENTRE_INTENTOS)
        except Exception as e:
            print(f"❌ Error en intento {intento}: {e}")
            time.sleep(ESPERA_ENTRE_INTENTOS)
    else:
        print(f"\n😔 No se pudo comprar después de {MAX_INTENTOS} intentos.")
