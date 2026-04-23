import json
import os

from django.core.management import call_command
from django.core.management.base import CommandError
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse


class ChatApiSecurityTests(TestCase):
	def setUp(self):
		self.user_model = get_user_model()
		self.user = self.user_model.objects.create_user(
			email="user1@example.com",
			nome="User 1",
			password="SenhaForte123!",
		)
		self.other = self.user_model.objects.create_user(
			email="user2@example.com",
			nome="User 2",
			password="SenhaForte123!",
		)

	def test_chat_mensagens_retorna_400_em_parametros_invalidos(self):
		self.client.force_login(self.user)
		response = self.client.get(reverse("api_chat_mensagens"), {"com": "abc", "desde": "xyz"})
		self.assertEqual(response.status_code, 400)

	def test_chat_enviar_exige_csrf(self):
		client = Client(enforce_csrf_checks=True)
		client.force_login(self.user)
		response = client.post(
			reverse("api_chat_enviar"),
			data=json.dumps({"destinatario_id": self.other.id, "mensagem": "Oi"}),
			content_type="application/json",
		)
		self.assertEqual(response.status_code, 403)

	def test_chat_mensagens_retorna_400_quando_desde_negativo(self):
		self.client.force_login(self.user)
		response = self.client.get(reverse("api_chat_mensagens"), {"com": str(self.other.id), "desde": "-1"})
		self.assertEqual(response.status_code, 400)

	def test_chat_enviar_retorna_400_quando_mensagem_ultrapassa_limite(self):
		self.client.force_login(self.user)
		response = self.client.post(
			reverse("api_chat_enviar"),
			data=json.dumps({"destinatario_id": self.other.id, "mensagem": "a" * 2001}),
			content_type="application/json",
		)
		self.assertEqual(response.status_code, 400)

	def test_chat_enviar_retorna_400_quando_envia_para_si_mesmo(self):
		self.client.force_login(self.user)
		response = self.client.post(
			reverse("api_chat_enviar"),
			data=json.dumps({"destinatario_id": self.user.id, "mensagem": "teste"}),
			content_type="application/json",
		)
		self.assertEqual(response.status_code, 400)


class ConfiguracoesUsuarioTests(TestCase):
	def setUp(self):
		self.user_model = get_user_model()
		self.admin = self.user_model.objects.create_superuser(
			email="admin@example.com",
			nome="Admin",
			password="SenhaForte123!",
		)

	def test_usuario_update_retorna_404_quando_pk_nao_existe(self):
		self.client.force_login(self.admin)
		response = self.client.get(reverse("configuracoes_usuario_editar", kwargs={"pk": 999999}))
		self.assertEqual(response.status_code, 404)


class AutorizacaoPorPapelTests(TestCase):
	def setUp(self):
		self.user_model = get_user_model()
		self.usuario_basico = self.user_model.objects.create_user(
			email="basico@example.com",
			nome="Basico",
			password="SenhaForte123!",
			nivel_acesso="usuario",
		)
		self.financeiro = self.user_model.objects.create_user(
			email="financeiro@example.com",
			nome="Financeiro",
			password="SenhaForte123!",
			nivel_acesso="financeiro",
		)

	def test_usuario_basico_recebe_403_no_financeiro(self):
		self.client.force_login(self.usuario_basico)
		response = self.client.get(reverse("financeiro_lancamentos"))
		self.assertEqual(response.status_code, 403)

	def test_usuario_basico_recebe_403_em_membros(self):
		self.client.force_login(self.usuario_basico)
		response = self.client.get(reverse("membros_listar"))
		self.assertEqual(response.status_code, 403)

	def test_usuario_financeiro_acessa_financeiro(self):
		self.client.force_login(self.financeiro)
		response = self.client.get(reverse("financeiro_lancamentos"))
		self.assertEqual(response.status_code, 200)


class BootstrapSecurityCommandTests(TestCase):
	def test_bootstrap_falha_sem_senha_com_debug_false(self):
		self.assertFalse(get_user_model().objects.filter(email="admin@igreja.com").exists())
		with self.settings(DEBUG=False):
			old_password = os.environ.pop("BOOTSTRAP_ADMIN_PASSWORD", None)
			old_email = os.environ.pop("BOOTSTRAP_ADMIN_EMAIL", None)
			try:
				with self.assertRaises(CommandError):
					call_command("bootstrap_sys_edah")
			finally:
				if old_password is not None:
					os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = old_password
				if old_email is not None:
					os.environ["BOOTSTRAP_ADMIN_EMAIL"] = old_email

	def test_bootstrap_usa_admin123_sem_senha_quando_debug_true(self):
		self.assertFalse(get_user_model().objects.filter(email="admin@igreja.com").exists())
		with self.settings(DEBUG=True):
			old_password = os.environ.pop("BOOTSTRAP_ADMIN_PASSWORD", None)
			old_email = os.environ.pop("BOOTSTRAP_ADMIN_EMAIL", None)
			try:
				call_command("bootstrap_sys_edah")
				admin = get_user_model().objects.get(email="admin@igreja.com")
				self.assertTrue(admin.check_password("admin123"))
			finally:
				if old_password is not None:
					os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = old_password
				if old_email is not None:
					os.environ["BOOTSTRAP_ADMIN_EMAIL"] = old_email
