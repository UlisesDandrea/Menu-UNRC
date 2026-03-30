import asyncio
import os
import json
from datetime import datetime
from playwright.async_api import async_playwright

# ─── Configuración ────────────────────────────────────────────────────────────
DNI      = os.environ.get("UNRC_DNI",      "TU_DNI_AQUI")
PASSWORD = os.environ.get("UNRC_PASSWORD", "TU_CONTRASENA_AQUI")
URL_MENU = "https://sisinfo.unrc.edu.ar/gisau/compra_menu.php"

# Supabase (opcional - si querés guardar en base de datos)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# ─── Scraper principal ─────────────────────────────────────────────────────────
async def obtener_menu():
    async with async_playwright() as p:
        # Lanzar navegador (headless=True para servidor)
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page    = await context.new_page()

        print("🌐 Abriendo página del menú...")
        await page.goto(URL_MENU, wait_until="networkidle")

        # ── Login con SAML ──────────────────────────────────────────────────
        # La página redirige automáticamente al login de SAML
        print("🔐 Detectando formulario de login...")

        # Esperar que aparezca el campo de usuario
        await page.wait_for_selector("input[type='text'], input[name*='user'], input[name*='dni'], input[id*='user']", timeout=15000)

        # Completar DNI
        campo_usuario = await page.query_selector("input[type='text']")
        if not campo_usuario:
            campo_usuario = await page.query_selector("input[name*='user']")
        await campo_usuario.fill(DNI)

        # Completar contraseña
        await page.fill("input[type='password']", PASSWORD)

        # Hacer click en el botón de login
        await page.click("button[type='submit'], input[type='submit']")

        print("⏳ Esperando redirección post-login...")
        await page.wait_for_load_state("networkidle")

        # ── Extraer el menú ────────────────────────────────────────────────
        print("🍽️  Extrayendo menú...")

        # Tomar screenshot del menú (útil si el menú es una tabla visual)
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        screenshot_path = f"menu_{fecha_hoy}.png"
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"📸 Screenshot guardado: {screenshot_path}")

        # Intentar extraer texto del menú
        # (ajustar el selector según la estructura real de la página)
        menu_texto = ""
        try:
            # Intentar con selectores comunes para tablas de menú
            selectores = [
                "table",
                ".menu",
                "#menu",
                "div.content",
                "div.main",
                "body"
            ]
            for selector in selectores:
                elemento = await page.query_selector(selector)
                if elemento:
                    menu_texto = await elemento.inner_text()
                    if len(menu_texto.strip()) > 50:  # Si tiene contenido relevante
                        break

        except Exception as e:
            print(f"⚠️  Error extrayendo texto: {e}")

        # Construir objeto con los datos del menú
        datos_menu = {
            "fecha":      fecha_hoy,
            "texto":      menu_texto.strip(),
            "screenshot": screenshot_path,
            "timestamp":  datetime.now().isoformat()
        }

        print("✅ Menú extraído correctamente")
        print("─" * 40)
        print(menu_texto[:500] if menu_texto else "(sin texto extraído, ver screenshot)")
        print("─" * 40)

        # Guardar en archivo JSON local
        with open(f"menu_{fecha_hoy}.json", "w", encoding="utf-8") as f:
            json.dump(datos_menu, f, ensure_ascii=False, indent=2)
        print(f"💾 Datos guardados en menu_{fecha_hoy}.json")

        # ── Guardar en Supabase (si está configurado) ──────────────────────
        if SUPABASE_URL and SUPABASE_KEY:
            await guardar_en_supabase(datos_menu)

        await browser.close()
        return datos_menu


async def guardar_en_supabase(datos):
    """Guarda el menú del día en Supabase."""
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
                print("☁️  Menú guardado en Supabase correctamente")
            else:
                print(f"⚠️  Error en Supabase: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"⚠️  No se pudo guardar en Supabase: {e}")


# ─── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    asyncio.run(obtener_menu())
