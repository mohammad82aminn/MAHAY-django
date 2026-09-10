from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    """
    Manager for MAHAY User model (login with mobile number).
    """

    use_in_migrations = True

    def _create_user(self, mobile_number, password, **extra_fields):
        if not mobile_number:
            raise ValueError("Mobile number is required")

        extra_fields["email"] = self.model.normalize_email_value(extra_fields.get("email"))
        user = self.model(mobile_number=mobile_number, **extra_fields)
        user.set_password(password)
        # Normalizes mobile/email and validates format, uniqueness and constraints
        user.full_clean()
        user.save(using=self._db)
        return user

    def create_user(self, mobile_number, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(mobile_number, password, **extra_fields)

    def create_superuser(self, mobile_number, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")

        return self._create_user(mobile_number, password, **extra_fields)