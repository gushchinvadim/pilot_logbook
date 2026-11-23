"""Invalidate existing API credentials when an account password changes."""
from django.conf import settings
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from rest_framework.authtoken.models import Token


@receiver(pre_save, sender=settings.AUTH_USER_MODEL, dispatch_uid='sim-password-before-save')
def remember_password_change(sender, instance, using, update_fields=None, **kwargs):
    instance._sim_password_changed = False
    if not instance.pk or (update_fields is not None and 'password' not in update_fields):
        return
    previous = sender.objects.using(using).filter(pk=instance.pk).values_list('password', flat=True).first()
    instance._sim_password_changed = previous is not None and previous != instance.password


@receiver(post_save, sender=settings.AUTH_USER_MODEL, dispatch_uid='sim-password-after-save')
def revoke_password_credentials(sender, instance, using, **kwargs):
    if getattr(instance, '_sim_password_changed', False):
        Token.objects.using(using).filter(user_id=instance.pk).delete()
        instance._sim_password_changed = False
