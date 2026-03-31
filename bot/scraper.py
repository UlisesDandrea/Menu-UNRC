import asyncio
import os
import json
from datetime import datetime
from playwright.async_api import async_playwright

DNI      = os.environ.get("UNRC_DNI",      "")
PASSWORD = os.environ.get("UNRC_PASSWORD", "")
URL_LOGIN = "https://sisinfo.unrc.edu.ar/gisau/compra_menu.php"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

async def obtener_menu():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page    = await context.new_page()

        # ── 1. Login ────────────────────────────────────────────────────────
        print("🌐 Abriendo página...")
        await page.goto(URL_LOGIN, wait_until="networkidle")

        print("🔐 Completando login...")
        await page.wait_for_selector("#nrodoc", timeout=15000)
        await page.fill("#nrodoc", DNI)
        await page.fill("#clave", PASSWORD)
        await page.click("button:has-text('Ingresar')")
        await page.wait_for_load_state("networkidle")
        print("✅ Login OK")

        # ── 2. Ir al comedor (GISAU) ────────────────────────────────────────
        print("🏫 Navegando al comedor...")
        await page.goto("https://sisinfo.unrc.edu.ar/gisau/index.php", wait_until="networkidle")

        # ── 3. Click en Compra menú diario ──────────────────────────────────
        print("🍽️ Entrando a Compra menú diario...")
        await page.click("a[href='compra_menu.php'], a[title='Compra de menú diario']")
        await page.wait_for_load_state("networkidle")

        # Tomar screenshot para ver qué hay en la página
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        await page.screenshot(path=f"menu_{fecha_hoy}.png", full_page=True)
        print("📸 Screenshot guardado")

        # ── 4. Extraer info del menú ─────────────────────────────────────────
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

        # ── 5. Intentar hacer la compra ──────────────────────────────────────
        print("🛒 Intentando comprar menú...")
        comprado = False
        try:
            # Buscar botón de compra (ajustar según la página real)
            boton = await page.query_selector(
                "button:has-text('Comprar'), "
                "input[value='Comprar'], "
                "a:has-text('Comprar'), "
                "button:has-text('Confirmar'), "
                "input[type='submit']"
            )
            if boton:
                await boton.click()
                await page.wait_for_load_state("networkidle")
                await page.screenshot(path=f"compra_{fecha_hoy}.png", full_page=True)
                print("✅ Compra realizada!")
                comprado = True
            else:
                print("⚠️ No se encontró botón de compra — puede que ya esté comprado o que la página sea distinta")
                print("📸 Revisá el screenshot para ver el estado actual")
        except Exception as e:
            print(f"⚠️ Error al comprar: {e}")

        # ── 6. Guardar datos ─────────────────────────────────────────────────
        datos_menu = {
            "fecha":     fecha_hoy,
            "texto":     menu_texto.strip(),
            "comprado":  comprado,
            "timestamp": datetime.now().isoformat()
        }

        with open(f"menu_{fecha_hoy}.json", "w", encoding="utf-8") as f:
            json.dump(datos_menu, f, ensure_ascii=False, indent=2)
        print(f"💾 Guardado en menu_{fecha_hoy}.json")

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
