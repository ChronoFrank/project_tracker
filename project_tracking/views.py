# -*- coding: utf-8 -*-
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from .serializers import UserProjectSerializer, TaskSerializer, ProjectSerializer
from django.contrib.auth.models import User
from .models import Task, Project
from datetime import datetime, timedelta
from django.utils import timezone


class UserProjectViewset(ModelViewSet):
    """
       list:
       Return a list of all the existing users and the related information about projects, tasks, spend time.

       retrieve:
       Return the given user and the related information about projects.
    """
    queryset = User.objects.all()
    serializer_class = UserProjectSerializer
    http_method_names = ['get', ]
    permission_classes = [IsAuthenticated, ]


class ProjectViewSet(ModelViewSet):
    """
       list:
       Return a list of all the existing projects for the authenticated user
       and the related information about projects, tasks, spend time.
       for the tasks that has been continue, the spend time will be added to the original.

       create:
       given a project name, this endpoint will create a new project instance for the authenticated user

    """
    permission_classes = [IsAuthenticated, ]
    http_method_names = ['get', 'post']
    serializer_class = ProjectSerializer
    queryset = Project.objects.all()

    def create(self, *args, **kwargs):
        validator = ProjectSerializer(data=self.request.data)
        if not validator.is_valid():
            return Response(validator.errors, status=status.HTTP_400_BAD_REQUEST)
        project = Project.objects.create(user=self.request.user, **validator.data)
        return Response(ProjectSerializer(instance=project).data, status=status.HTTP_201_CREATED)

    def list(self, request, *args, **kwargs):
        query_set = self.get_queryset().filter(user=request.user)
        page = self.paginate_queryset(query_set)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(query_set, many=True)
        return Response(data=serializer.data, status=status.HTTP_200_OK)


class TasksViewSet(ModelViewSet):
    """
       list:
       Return a list of all the existing tasks for the authenticated user.

       create:
       Given a projet_id this enpoint will create a new task. some parameters are
       *project_id (required) id to link the task to an existing project
       *name (optional) task name
       *duration (optional) time in format H:M:S to specify the task duration.

    """
    permission_classes = [IsAuthenticated, ]
    http_method_names = ['get', 'post', 'put']
    serializer_class = TaskSerializer
    queryset = Task.objects.all()

    def list(self, request, *args, **kwargs):
        query_set = self.get_queryset().filter(project__user=request.user).order_by('-started_at')
        page = self.paginate_queryset(query_set)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(query_set, many=True)
        return Response(data=serializer.data, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        running_tasks = Task.objects.filter(project__user=request.user, ended_at__isnull=True, paused_at__isnull=True)
        if running_tasks.exists():
            return Response({'error': 'there are tasks running, '
                                      'you must pause or close'
                                      ' them in order to create new tasks'}, status=status.HTTP_403_FORBIDDEN)
        else:
            project_id = request.data.get('project_id')
            task_name = request.data.get('name')
            duration = request.data.get('duration')
            if not project_id:
                return Response({'error': 'You must provide a project'
                                          ' in order to start a new task'}, status=status.HTTP_400_BAD_REQUEST)
            else:
                started_at = timezone.now()
                params = {
                    "started_at": started_at
                }
                if task_name:
                    params.update({"name": task_name})
                try:
                    project = Project.objects.get(id=int(project_id), user=self.request.user)
                    params.update({"project": project})
                except (Project.DoesNotExist, ValueError) as e:
                    return Response({'error': 'Invalid Project'}, status=status.HTTP_400_BAD_REQUEST)

                if duration:
                    try:
                        time_obj = datetime.strptime('01:15:05', '%H:%M:%S')
                        ended_at = started_at + timedelta(hours=time_obj.hour,
                                                          minutes=time_obj.minute,
                                                          seconds=time_obj.second)
                        params.update({"ended_at": ended_at})
                    except ValueError:
                        return Response({'error': 'Invalid duration, format must be H:M:S'},
                                        status=status.HTTP_400_BAD_REQUEST)

                new_task = Task.objects.create(**params)
            return Response(TaskSerializer(instance=new_task).data, status=status.HTTP_201_CREATED)

    @action(methods=['put', ], detail=False, url_path='pause_resume/(?P<pk>\d+)')
    def pause_resume_task(self, request, pk):
        """
        put:
        given a task id, this endpoint will pause or unpause a task
        (update the paused_at and seconds_paused fields in the model)
        """
        try:
            task = Task.objects.get(id=int(pk), project__user=request.user)
        except Task.DoesNotExist:
            return Response({'error': 'Task not found'}, status=status.HTTP_404_NOT_FOUND)

        if not task.is_closed:
            task.toggle_paused()
            return Response(TaskSerializer(instance=task).data, status=status.HTTP_200_OK)
        else:
            return Response({'error': 'the task is already closed'}, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=['put', ], detail=False, url_path='close/(?P<pk>\d+)')
    def close_task(self, request, pk):
        """
       put:
       given a task id, this endpoint will close task (update ended_at field with the current date and time).
       """
        try:
            task = Task.objects.get(id=int(pk), project__user=request.user)
        except Task.DoesNotExist:
            return Response({'detail': 'Task not found'}, status=status.HTTP_404_NOT_FOUND)
        if not task.is_closed:
            task.close()
            return Response(TaskSerializer(instance=task).data, status=status.HTTP_200_OK)
        else:
            return Response({'error': 'Task already closed'}, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=['put', ], detail=False, url_path='restart/(?P<pk>\d+)')
    def restart_task(self, request, pk):
        """
            put:
            given a task id, this endpoint will update the fileds started_at, ended_at,
             seconds_paused and paused_at, to the default values
       """
        try:
            task = Task.objects.get(id=int(pk), project__user=request.user)
        except Task.DoesNotExist:
            return Response({'detail': 'Task not found'}, status=status.HTTP_404_NOT_FOUND)

        if not task.is_closed:
            task.restart()
            return Response(TaskSerializer(instance=task).data, status=status.HTTP_200_OK)
        else:
            return Response({'error': 'Task already closed'}, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=['post', ], detail=False, url_path='continue')
    def continue_task(self, request):
        """
            post:
            given a task id, this endpoint will take a closed task and start a new one associated to the closed one
       """
        running_tasks = Task.objects.filter(project__user=request.user, ended_at__isnull=True, paused_at__isnull=True)
        if running_tasks.exists():
            return Response({'error': 'there are tasks running, '
                                      'you must pause or close'
                                      ' them in order to create new tasks'}, status=status.HTTP_403_FORBIDDEN)
        else:
            task_id = request.data.get('id')
            if not task_id:
                return Response({'error': 'You must provide a task id'
                                          ' in order to continue task'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                task = Task.objects.get(id=int(task_id), project__user=request.user, ended_at__isnull=False)
            except Task.DoesNotExist:
                return Response({'error': 'Task not found'}, status=status.HTTP_404_NOT_FOUND)

            kwargs = {
                'name': task.name,
                'project': task.project,
                'cloned_from': task,
                'started_at': timezone.now()
            }
            new_task = Task.objects.create(**kwargs)
            return Response(TaskSerializer(instance=new_task).data, status=status.HTTP_201_CREATED)




