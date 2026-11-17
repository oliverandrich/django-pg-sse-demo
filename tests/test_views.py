from test_plus.test import TestCase


class SmokeTest(TestCase):
    def test_join_page_renders(self):
        self.get("/join/")
        self.assertResponseContains("Join the chat", html=False)

    def test_admin_login_renders(self):
        self.get_check_200("admin:login")
