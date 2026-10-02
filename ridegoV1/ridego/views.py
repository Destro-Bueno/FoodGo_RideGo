"""
`ridego.views` — a camada VIEW do padrão MVC, num único arquivo.

Cada tela do app é uma classe que herda de `BaseView` e implementa o
método `build()`. As Views só desenham a interface e encaminham eventos do
usuário para o `RideController` — nunca calculam preço, nunca acessam o
histórico diretamente, nunca decidem regra de negócio sozinhas.

Está dividido em blocos, na ordem em que um bloco depende do anterior:

1. `Theme`      — paleta de cores + componentes visuais reutilizados
2. `BaseView`   — classe abstrata da qual toda tela herda
3. `SplashView`, `HomeView`, `CategoriesView`, `MatchingView`, `RateView`,
   `HistoryView` — uma classe por tela, na ordem do fluxo do app
"""


from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

import flet as ft
import flet_map as ftm

from ridego.controller import RideController
from ridego.model import CATEGORIES, QUICK_DESTINATIONS, Destination, Ride, RideCategory
from ridego.services import AddressNotFoundError

# -------------------------------------------------------------------------
# 1) Tema visual + componentes reutilizados
# -------------------------------------------------------------------------


class theme:
    """ 
    Paleta de cores + fábrica de componentes visuais do app.
    
    Todas as cores e os métodos utilitários são atribuidos?métodos de 
    CLASSE (não de instância): não faz sentido ter "duas paletas de cores" 
    coexistindo, então nunca precisamos instanciar 'Theme()' - usamos 
    sempre 'Theme, PRIMARY' , 'Theme.soft_card(...)', etc.
    """

    # -- Paleta de cores -------------------------------------------------------------------
    PRIMARY = "#582186"
    PRIMARY_DARK = "#3B0764"
    ACCENT = "#06B6D4"
    SUCCESS = "#10B981"
    WAITING = "#F59E0B"
    DANGER = "#EF4444"
    BG = "#F5F3FB"
    INK = "#1F2937"
    MUTED = "#6B7280"

    # cada categoria de corrida ganha uma cor primária - ajuda o usuário a
    # identificar rapidamente a categoria que ele escolheu sem precisar de texto
    CATEGORY_COLORS = {
        "economico": ACCENT,
        "comfort": PRIMARY,
        "x1": DANGER,
    }

    OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

    @classmethod
    def color_for_category(cls, category_id: str) -> str:
        """Cor de assinatura de uma categoria (com fallback para a cor de marca)."""
        return cls.CATEGORY_COLORS.get(category_id, cls.PRIMARY)

    # -- Tema global do flet (Material 3) -----------------------------    
    @classmethod
    def build_flet_theme(cls) -> ft.Theme:
        """
        Monta o tema global do app. Aplicado uma única vez em 'page.theme',
        garante que todo 'ft.Button', 'AppBr', etc. no app inteiro herdem
        o mesmo visual sem precisar repetir 'style=...' em cada widget.
        """
        return ft.Theme(
            color_scheme_seed=cls.PRIMARY,
            use_material3=True,
            color_scheme=ft.ColorScheme(primary=cls.PRIMARY, secondary=cls.ACCENT),
            appbar_theme=ft.AppBarTheme(
                bgcolor=ft.Colors.TRANSPARENT,
                elevation=0,
                center_title=True,
                title_text_style=ft.TextStyle(size=20, weight=ft.FontWeight.W_800, color=cls.INK),
            ),
            button_theme=ft.ButtonTheme(
                style=ft.ButtonStyle(
                    bgcolor=cls.PRIMARY,
                    color=ft.Colors.WHITE,
                    padding=ft.Padding(24, 18, 24, 18),
                    shape=ft.RoundedRectangleBorder(radius=16),
                    text_style=ft.TextStyle(size=15, weight=ft.FontWeight.BOLD),
                    elevation=0,
                )
            ),
            text_button_theme=ft.TextButtonTheme(
                style=ft.ButtonStyle(
                    color=cls.ACCENT,
                    text_style=ft.TextStyle(size=15, weight=ft.FontWeight.W_600),
                )
            ),
        )

    # -- Componentes visuais reutilizados ---------------------------------------------------
    @staticmethod
    def soft_card(content: ft.Control, padding: int = 16, radius: int = 20, on_click= None) -> ft.Container:
        """
        "Cartão" branco padrão do app: cantos arrendondados + sombra suave.
        'on_click' é opcional - quando informado, o cartão inteiro fica
        clicável (o clique precisa ficar no Container, não no Row/Column interno).
        """
        return ft.Container(
            padding=padding,
            border_radius=radius,
            bgcolor=ft.Colors.WHITE,
            on_click=on_click,
            shadow=ft.BoxShadow(
                blur_radius=18,
                spread_radius=0,
                colors=ft.Colors.with_opacity(0.08, Theme.INK),
                offset=ft.Offset(0, 6),
            ),
            content=content,
        )

    @staticmethod
    def icon_badge(icon, color: str, size: int = 44) -> ft.Container:
        """Circulo colorido com ícone centralizado, usado para representar categorias de corrida."""
        return ft.Container(
            width=size,
            height=size,
            border_radius=size / 2,
            bgcolor=ft.color.with_opacity(0.12, color),
            alignment=ft.alignment.CENTER,
            content=ft.Icon(icon, color=ft.Colors.WHITE, size=size * 0.55),
        )

    @staticmethod
    def eyebrow(text: str) -> ft.Text:
        """Rótulo pequeno, em maiusculas, usado para identificar seções da tela."""
        return ft.text(
            text.upper(),
            size=12,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.with_opacity(0.75, ft.Colors.WHITE),
            letter_spacing=1.2,
        )

    @staticmethod
    def lation(coords: tuple[float, float]) -> ftm.MapLatitudeLongitude:
        """Converte uma tupla (lat, lon) no tipo esperado pelo flet_map."""
        return ftm.MapLatitudeLongitude(coords[0], coords[1])


# -------------------------------------------------------------------------
# 2) Classe-base de uma tela
# -------------------------------------------------------------------------


class BaseView(ABC):
    """
    Classe-base de uma tela do app.
    
    Toda subclasse recebe a página do flet ('page') e o 'RideController'
    Já prontos (injeção de dependência) - nenhuma tela cria o seu próprio
    contoller, e nenhuma tela acessa o Model diretamente.

    três pilares de Orientação a Objetos aparecem aqui:

    * ABSTRAÇÃO: 'BaseView' declara o "contrato" que toda tela precisa
    cumprir ('route' e 'build()'), sem se preocupar com os detalhes de 
    cada tela.
    *HERANÇA: todas as telas abaixo reaproveitam essa estrutura comum
    (guardar 'page'/'contoller', expor 'route') em vez de repeti-lá.
    *POLIMORFISMO: o roteador do app ('App', em 'app.py') chama
    'view.build()' do mesmo jeito para qualquer tela - cada subcalsse
    decide sozinha como construir o seu próprio 'ft.View', mas quem 
    chama não precisa saber (nem se importar) com qual subcalsse está
    lidando.
    """

    #: rota flet desta tela (ex.: "/" "/categorias"). Sobrecrita nas subcalsses.
    route: str = "/"

    def __init__(self, page: ft.Page, contoller: RideController) -> None:
        self.page = page
        self.controller = controller

    @abstractmethod
    def build(self) -> ft.View:
        """
        Constrói e devolve o 'ft.View' desta tela. Toda subclasse concreta
        é OBRIGADA a implementar este método (é o que torna 'Baseview'
        uma calsse abstrata de verdade: 'BaseView'(page, controller)'
        sozinha não pode ser instaciada).
        """
        raise NotImplementedError


# -------------------------------------------------------------------------
# 3) Telas concretas do app
# -------------------------------------------------------------------------


class SplashView(BaseView):
    """
    Tela de abertura com o gradiente de marca, um "selo" com ícone que 
    entra em cena com uma animação sutil de escala, e um indicador de 
    carregamento discreto.
    
    Diferente das demais telas, esta não fica assiciada a uma rota do
    roteador ('sef.route' não é usada) - ela é mostrada diretamente pela
    'App' durante a inicialização e nunca entra no historico de navegação,
    então o botão "voltar" nunca cai nela.
    """

    SPLASH_DURATION_SECONDS = 3 

    def __init__(self, page: ft.Page, controller: RideController) -> None:
        super().__init__(page, controller)
        # Guardamos a referência do "selo" animado como atributo de
        # instância para poder disparar a animação de entrada depois que a 
        # tela já estiver desenhada (ver 'play_intro_and_wait').
        self._logo_badge: ft.Container | None = None

    def build(self) -> ft.View:
        self._logo_badge = ft.Container(
            width=112,
            height=112,
            border_radius=56,
            alignment=ft.alignment.CENTER,
            bgcolor=ft.Colors.with_opacity(0.16, Theme.WHITE),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.35, ft.Colors.WHITE)),
            content=ft.Icon(ft.icons.DIRECTIONS_CAR_FILLED, color=ft.Colors.WHITE, size=58),
            scale=0.6,  # começa invisível, vai crescer com animação
            opacity=0,  # começa invisível, vai aparecer com animação
            animate_scale=ft.Animation(650, ft.AnimationCurve.EASE_OUT_BACK),
            animate_opacity=ft.Animation(500, ft.AnimationCurve.EASE_OUT),
        )
        brand_column = ft.Column(
            horizontal_aligment=ft.CrossAxisAlignment.CENTER,
            spacing=6
            controls=[
                ft.Text("RideGo", size=36, weight=ft.fontWeight.W_900, color=ft.Colors.WHITE),
                ft.text(
                    "Sua próxima corrida, a poucos toques",
                    size=13,
                    color=ft.Colors.with_opacity(0.85, ft.Colors.WHITE),
                ),
            ],
        )
        spinner = ft.ProgressRing(width=24, height=24, stroke_width=3, color=ft.Colors.WHITE)

        return ft.View(
            route="/splash"
            bgcolor=Theme.PRIMARY_DARK,
            padding=0,
            controls=[
                ft.Container(
                    expand=True,
                    gradient=ft.LinearGradiant(
                        colors=[Theme.PRIMARY_DARK, Theme.PRIMARY],
                        begin=ft.Aligment.TOP_CENTER,
                        end=ft.Aligment.BOTTOM_CENTER,
                    ),
                    alignment=ft.Aligment.CENTER,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAligment.CENTER,
                        aligment=ft.MainAxisAligment.CENTER,
                        spacing=,
                        controls=[self.__logo__badge, brand_column, spinner],
                    )
                )
            ],
        )

    async def play_intro_and_wait(self) -> None:
        """
        Dispara a animação da entrada do "selo" e aguarda o tempo toal da
        splash ('SPLASH_DURATION_SECONDS'). Chamado pela 'App' logo depois
        de build()' Já sido inserido em 'page.Views'.
        """
        self.page.update()
        await asyncio.sleep(0.85)
        self.__logo__badge.scale = 1
        self.__logo__badge.opacity = 1
        self.page.update()
        await asyncio.sleep(self.SPLASH_DURATION_SECONDS)


class HomeView(BaseView):
    """
    Tela "Para onde vamos"?: mostra o mapa com a origem do suário e deixa
    escolher um destino de duas formas - tocando num "chip" rápido ou 
    digitando um endereço livremente (resolvido de verdade via geocodificação).
    """

    route = "/"