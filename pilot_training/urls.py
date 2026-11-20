# urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.authtoken.views import obtain_auth_token
from . import views, crew_views, portal_views, revision_views
from .views import download_template, get_sessions_for_pilot, pilot_analytics_view
from .views import PublicObtainAuthToken


router = DefaultRouter()
router.register(r'pilots', views.PilotViewSet)
router.register(r'instructors', views.InstructorViewSet)
router.register(r'exercises', views.ExerciseViewSet)
router.register(r'sessions', views.SessionViewSet)

app_name = 'pilot_training'



urlpatterns = [
    path('', views.index_page, name='index'),

    # 🔻 Сначала — кастомные пути (важно!)
    path('admin/reports/training/<int:pilot_id>/', views.training_report, name='training_report'),
    path('admin/analytics/', pilot_analytics_view, name='pilot_analytics'),
    path('admin/download-template/', download_template, name='download-template'),
    path('admin/manage-uploads/', views.manage_uploads, name='manage_uploads'),


    path('api/my-training-sessions/', portal_views.my_training_sessions, name='my_training_sessions'),
    path('api/auth/me/', portal_views.current_user, name='current_user'),
    path('api/results/<int:pk>/acknowledge/', revision_views.acknowledge_result, name='acknowledge_result'),
    path('api/results/<int:pk>/revisions/', revision_views.revisions, name='result_revisions'),
    path('api/results/', portal_views.results, name='results'),
    path('api/results/<int:pk>/print/', portal_views.print_result, name='print_result'),
    path('api/results/<int:pk>/print-access/', portal_views.prepare_result_print, name='prepare_result_print'),
    path('api/training-sessions/<int:pk>/', portal_views.training_detail, name='training_detail'),
    path('api/sessions/available/', views.available_sessions),
    path('api/session/<int:session_id>/exercises/', views.session_exercises),
    path('api/rating-sessions/', views.create_rating_session),
    path('api/rating-sessions/by-pilot/', views.ratings_by_pilot),
    path('api/crew-sessions/', crew_views.crew_sessions, name='crew_sessions'),
    path('api/training-sessions/', views.training_sessions_for_instructor),
    path('api/pilots/', views.pilot_list),
    path('api/pilots/<int:pk>/', views.pilot_detail),
    path('api/sessions-for-pilot/', get_sessions_for_pilot, name='get_sessions_for_pilot'),
    path('admin/trainings/sessions/calendar-data/', views.training_session_calendar_data,
         name='training_session_calendar_data'),
    path('print-rating-token/<uuid:token>/', views.print_rating_by_token, name='print_rating_token'),
    path('print-rating-unsafe/<int:rating_id>/', views.print_rating_clean, name='print_rating_clean'),
    path('pilot-partial/', views.pilot_partial, name='pilot_partial'),

    path('api/docs/', views.get_docs_list, name='docs_list'),
    path('admin/upload-pdf/', views.upload_pdf, name='upload_pdf'),
    path('admin/manage-docs/', views.manage_docs, name='manage_docs'),
    path('pilot-search/', views.pilot_search, name='pilot_search'),
    # 🔺 Потом — router (чтобы он не перехватывал кастомные пути)
    path('api/', include(router.urls)),

    # Авторизация
    path('api/api-token-auth/', PublicObtainAuthToken.as_view(), name='api-token-auth'),
    path('api/instructor/current/', views.current_instructor),
]
