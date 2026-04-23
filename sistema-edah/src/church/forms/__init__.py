from .auth import EmailAuthenticationForm
from .cadastros import (
    CasalForm,
    FamiliaForm,
    FamiliaMembroForm,
    FuncionarioForm,
    IgrejaForm,
    LiderForm,
    MembroForm,
    PessoaForm,
    VisitanteForm,
)
from .comunicacao import (
    GaleriaFotoForm,
    GaleriaForm,
    MensagemForm,
    NoticiaForm,
    PedidoOracaoForm,
)
from .cursos import (
    CertificadoForm,
    CursoAulaForm,
    CursoForm,
    CursoMatriculaForm,
    CursoModuloForm,
    CursoNotaForm,
    CursoPresencaForm,
)
from .discipulado import ClasseAlunoForm, ClasseEstudoForm, DiscipuladoForm
from .eventos import EventoForm, EventoInscricaoForm, EventoResponsavelForm
from .financeiro import CategoriaFinanceiraForm, LancamentoFinanceiroForm
from .ministerios_grupos import (
    MinisterioForm,
    MinisterioMembroForm,
    PequenoGrupoForm,
    PequenoGrupoMembroForm,
)
from .user_settings import UserAdminForm, UserCreateForm, UserPasswordForm, UserProfileForm

__all__ = [
    "EmailAuthenticationForm",
    "PessoaForm",
    "MembroForm",
    "VisitanteForm",
    "LiderForm",
    "FuncionarioForm",
    "FamiliaForm",
    "FamiliaMembroForm",
    "CasalForm",
    "IgrejaForm",
    "DiscipuladoForm",
    "ClasseEstudoForm",
    "ClasseAlunoForm",
    "MinisterioForm",
    "MinisterioMembroForm",
    "PequenoGrupoForm",
    "PequenoGrupoMembroForm",
    "LancamentoFinanceiroForm",
    "CategoriaFinanceiraForm",
    "CursoForm",
    "CursoModuloForm",
    "CursoAulaForm",
    "CursoMatriculaForm",
    "CursoPresencaForm",
    "CursoNotaForm",
    "CertificadoForm",
    "EventoForm",
    "EventoResponsavelForm",
    "EventoInscricaoForm",
    "NoticiaForm",
    "PedidoOracaoForm",
    "GaleriaForm",
    "GaleriaFotoForm",
    "MensagemForm",
    "UserProfileForm",
    "UserPasswordForm",
    "UserAdminForm",
    "UserCreateForm",
]
