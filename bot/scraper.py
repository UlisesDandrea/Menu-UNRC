import asyncio
import os
import json
from datetime import datetime
from playwright.async_api import async_playwright

DNI      = os.environ.get("UNRC_DNI",      "")
PASSWORD = os.environ.get("UNRC_PASSWORD", "")
URL_MENU = "https://sisinfo.unrc.edu.ar/gisau/compra_menu.php"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

async def obtener_menu():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page    = await context.new_page()

        print("🌐 Abriendo página del menú...")
        await page.goto(URL_MENU, wait_until="networkidle")

        print("🔐 Completando login...")
        await page.wait_for_selector("#nrodoc", timeout=15000)
        await page.fill("#nrodoc", DNI)
        await page.fill("input[name='MenuSis.clave']", PASSWORD)
        await page.click("button:has-text('Ingresar'), input[type='submit']")

        print("⏳ Esperando redirección...")
        await page.wait_for_load_state("networkidle")

        print("🍽️ Extrayendo menú...")
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        screenshot_path = f"menu_{fecha_hoy}.png"
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"📸 Screenshot guardado: {screenshot_path}")

        menu_texto = ""
        try:
            for selector in ["table", ".menu", "#menu", "div.content", "body"]:
                elemento = await page.query_selector(selector)
                if elemento:
                    texto = await elemento.inner_text()
                    if len(texto.strip()) > 50:
                        menu_texto = texto
                        break
        except Exception as e:
            print(f"⚠️ Error extrayendo texto: {e}")

        datos_menu = {
            "fecha":      fecha_hoy,
            "texto":      menu_texto.strip(),
            "screenshot": screenshot_path,
            "timestamp":  datetime.now().isoformat()
        }

        print("✅ Listo!")
        print(menu_texto[:500] if menu_texto else "(ver screenshot)")

        with open(f"menu_{fecha_hoy}.json", "w", encoding="utf-8") as f:
            json.dump(datos_menu, f, ensure_ascii=False, indent=2)

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
