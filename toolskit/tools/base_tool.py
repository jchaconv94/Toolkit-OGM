"""
base_tool.py
============
Clase abstracta que define el contrato que toda herramienta
del ToolKit SISMED debe cumplir.

Cualquier nueva herramienta que quieras añadir solo necesita:
  1. Heredar de SismedTool
  2. Implementar los métodos abstractos
  3. Registrarse en tools/__init__.py

Esto garantiza que el "motor" principal (main.py) nunca
necesite ser modificado para conocer los detalles de
una herramienta específica.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import flet as ft


@dataclass
class ToolMetadata:
    """
    Ficha de identidad de una herramienta.
    El motor la utiliza para renderizar tarjetas, tooltips y el buscador.
    """
    nombre: str                       # Nombre corto para mostrar en tarjetas/menú
    descripcion: str                  # Descripción breve (aparece bajo el nombre en la tarjeta)
    icono: str                        # ft.icons.XXXX
    color: str                        # ft.colors.XXXX  (color de acento)
    categoria: str                    # Ej: "Herramientas" | "Reports SISMED"
    etiquetas: list[str] = field(default_factory=list)  # Para el buscador


class SismedTool(ABC):
    """
    Clase base abstracta para todas las herramientas del ToolKit.

    Subclases deben implementar:
      - metadata  →  Propiedad que devuelve un ToolMetadata
      - build_view(page, navigate_fn)  →  Devuelve el ft.Control (vista completa)
    """

    @property
    @abstractmethod
    def metadata(self) -> ToolMetadata:
        """
        Retorna la ficha descriptiva de la herramienta.
        """
        ...

    @abstractmethod
    def build_view(self, page: ft.Page, navigate_fn) -> ft.Control:
        """
        Construye y devuelve la vista completa de la herramienta
        lista para insertarse en el área de contenido principal.

        Parámetros:
          - page        : la instancia ft.Page activa
          - navigate_fn : función navigate(idx) del sistema de navegación
                          para que la herramienta pueda volver atrás o
                          abrir otras secciones

        Retorna un ft.Control (usualmente ft.Container) que representa
        la pantalla completa de la herramienta.
        """
        ...

    # ─── Helpers opcionales que las subclases pueden reutilizar ───────────────

    def _back_button(self, label: str, navigate_fn, target_idx: int) -> ft.Control:
        """Botón estándar de retroceso premium con diseño de cápsula y efecto hover subtle."""
        
        def on_hover(e):
            e.control.bgcolor = ft.colors.with_opacity(0.25, ft.colors.WHITE) if e.data == "true" else ft.colors.with_opacity(0.1, ft.colors.WHITE)
            e.control.border  = ft.border.all(1, ft.colors.with_opacity(0.3, ft.colors.WHITE) if e.data == "true" else ft.colors.with_opacity(0.15, ft.colors.WHITE))
            e.control.update()

        return ft.Container(
            content=ft.Row([
                ft.Icon(ft.icons.ARROW_BACK_ROUNDED, size=16, color=ft.colors.WHITE),
                ft.Text(label, size=12, weight=ft.FontWeight.W_700, color=ft.colors.WHITE)
            ], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
            padding=ft.padding.symmetric(horizontal=18, vertical=10),
            border_radius=25,
            bgcolor=ft.colors.with_opacity(0.1, ft.colors.WHITE),
            border=ft.border.all(1, ft.colors.with_opacity(0.15, ft.colors.WHITE)),
            on_click=lambda _: navigate_fn(target_idx),
            on_hover=on_hover,
            animate=ft.animation.Animation(200, ft.AnimationCurve.EASE_OUT_QUAD)
        )

    def _section_header(self, icon_name: str, icon_color: str,
                         title: str, subtitle: str = "",
                         right_content: ft.Control = None) -> ft.Control:
        """Cabecera premium estandarizada para todas las herramientas."""
        
        main_row_controls = [
            ft.Container(
                content=ft.Icon(icon_name, size=38, color=icon_color),
                bgcolor=ft.colors.with_opacity(0.14, icon_color),
                border_radius=14,
                padding=12,
            ),
            ft.Container(width=15),
            ft.Column([
                ft.Text(title, size=28, weight=ft.FontWeight.W_900, color=ft.colors.WHITE),
                ft.Text(subtitle, size=13, color=ft.colors.GREY_400) if subtitle else ft.Container(),
            ], spacing=2)
        ]
        
        if right_content:
            main_row_controls.append(ft.Container(expand=True))
            main_row_controls.append(right_content)

        return ft.Container(
            border_radius=20,
            gradient=ft.LinearGradient(
                begin=ft.alignment.center_left,
                end=ft.alignment.center_right,
                colors=["#0D1B2A", "#111827"],
            ),
            padding=ft.padding.only(top=24, bottom=24, left=30, right=30),
            content=ft.Row(
                main_row_controls, 
                vertical_alignment=ft.CrossAxisAlignment.CENTER
            )
        )
