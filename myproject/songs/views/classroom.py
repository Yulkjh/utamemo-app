from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from datetime import datetime

from ..models import Song, Classroom, ClassroomMembership, ClassroomSong, ClassroomAssignment
from ..content_filter import check_name_for_inappropriate_content
import random
import string


def _is_teacher_user(user):
    return getattr(user, 'is_teacher', False) or user.is_staff


def _can_use_classroom(user):
    return user.is_school or _is_teacher_user(user)

def generate_classroom_code():
    """ユニークなクラスコードを生成"""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not Classroom.objects.filter(code=code).exists():
            return code


@login_required
def classroom_list(request):
    """参加中のクラス一覧"""
    app_language = request.session.get('app_language', 'ja')
    is_english = app_language == 'en'
    is_chinese = app_language == 'zh'
    
    # スクールプラン or 先生権限限定
    if not _can_use_classroom(request.user):
        if is_english:
            messages.warning(request, 'Classroom feature is available for School Plan users or teacher accounts only.')
        elif is_chinese:
            messages.warning(request, '教室功能仅限学校计划用户或教师账号使用。')
        else:
            messages.warning(request, 'クラス機能はスクールプランまたは先生権限ユーザー限定です。')
        return redirect('users:upgrade')
    
    # ホストしているクラス
    hosted_classrooms = Classroom.objects.filter(host=request.user, is_active=True)
    # 参加しているクラス
    joined_classrooms = request.user.joined_classrooms.filter(is_active=True).exclude(host=request.user)
    
    return render(request, 'songs/classroom_list.html', {
        'hosted_classrooms': hosted_classrooms,
        'joined_classrooms': joined_classrooms,
        'is_english': is_english,
        'is_chinese': is_chinese,
    })


@login_required
def classroom_join(request):
    """クラスに参加"""
    app_language = request.session.get('app_language', 'ja')
    is_english = app_language == 'en'
    is_chinese = app_language == 'zh'
    
    # スクールプラン or 先生権限限定
    if not _can_use_classroom(request.user):
        if is_english:
            messages.warning(request, 'Classroom feature is available for School Plan users or teacher accounts only.')
        elif is_chinese:
            messages.warning(request, '教室功能仅限学校计划用户或教师账号使用。')
        else:
            messages.warning(request, 'クラス機能はスクールプランまたは先生権限ユーザー限定です。')
        return redirect('users:upgrade')
    
    if request.method == 'POST':
        code = request.POST.get('code', '').strip().upper()
        
        if not code:
            if is_english:
                messages.error(request, 'Please enter a class code.')
            elif is_chinese:
                messages.error(request, '请输入班级代码。')
            else:
                messages.error(request, 'クラスコードを入力してください。')
            return redirect('songs:classroom_join')
        
        try:
            classroom = Classroom.objects.get(code=code, is_active=True)
            
            # 既に参加しているか確認
            if ClassroomMembership.objects.filter(user=request.user, classroom=classroom).exists():
                if is_english:
                    messages.info(request, 'You are already a member of this class.')
                elif is_chinese:
                    messages.info(request, '您已经是该班级的成员。')
                else:
                    messages.info(request, '既にこのクラスに参加しています。')
            else:
                ClassroomMembership.objects.create(user=request.user, classroom=classroom)
                if is_english:
                    messages.success(request, f'You have joined "{classroom.name}"!')
                elif is_chinese:
                    messages.success(request, f'已加入"{classroom.name}"！')
                else:
                    messages.success(request, f'「{classroom.name}」に参加しました！')
            
            return redirect('songs:classroom_detail', pk=classroom.pk)
            
        except Classroom.DoesNotExist:
            if is_english:
                messages.error(request, 'Invalid class code.')
            elif is_chinese:
                messages.error(request, '无效的班级代码。')
            else:
                messages.error(request, '無効なクラスコードです。')
    
    return render(request, 'songs/classroom_join.html', {
        'is_english': is_english,
        'is_chinese': is_chinese,
    })


@login_required
def classroom_create(request):
    """クラスを作成（先生権限ユーザーのみ）"""
    app_language = request.session.get('app_language', 'ja')
    is_english = app_language == 'en'
    is_chinese = app_language == 'zh'
    
    # 先生権限のチェック（運営が付与）
    if not _is_teacher_user(request.user):
        if is_english:
            messages.error(request, 'Teacher permission is required to create classes.')
        elif is_chinese:
            messages.error(request, '创建班级需要教师权限。')
        else:
            messages.error(request, 'クラス作成には先生権限が必要です。運営に付与をご依頼ください。')
        return redirect('users:upgrade')
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        
        if not name:
            if is_english:
                messages.error(request, 'Please enter a class name.')
            elif is_chinese:
                messages.error(request, '请输入班级名称。')
            else:
                messages.error(request, 'クラス名を入力してください。')
            return redirect('songs:classroom_create')
        
        # 卑語・不適切ワードチェック
        name_check = check_name_for_inappropriate_content(name)
        if name_check['is_inappropriate']:
            if is_english:
                messages.error(request, 'This class name contains inappropriate language. Please choose a different name.')
            elif is_chinese:
                messages.error(request, '此班级名称包含不当用语，请选择其他名称。')
            else:
                messages.error(request, 'このクラス名には不適切な言葉が含まれています。別の名前を入力してください。')
            return redirect('songs:classroom_create')
        
        code = generate_classroom_code()
        classroom = Classroom.objects.create(
            name=name,
            description=description,
            code=code,
            host=request.user
        )
        # ホスト自身もメンバーとして追加
        ClassroomMembership.objects.create(user=request.user, classroom=classroom)
        
        if is_english:
            messages.success(request, f'Class created! Share code: {code}')
        elif is_chinese:
            messages.success(request, f'班级已创建！分享代码：{code}')
        else:
            messages.success(request, f'クラスを作成しました！参加コード: {code}')
        
        return redirect('songs:classroom_detail', pk=classroom.pk)
    
    return render(request, 'songs/classroom_create.html', {
        'is_english': is_english,
        'is_chinese': is_chinese,
    })


@login_required
def classroom_detail(request, pk):
    """クラス詳細（楽曲一覧）"""
    app_language = request.session.get('app_language', 'ja')
    is_english = app_language == 'en'
    is_chinese = app_language == 'zh'
    
    # スクールプラン or 先生権限限定
    if not _can_use_classroom(request.user):
        if is_english:
            messages.warning(request, 'Classroom feature is available for School Plan users or teacher accounts only.')
        elif is_chinese:
            messages.warning(request, '教室功能仅限学校计划用户或教师账号使用。')
        else:
            messages.warning(request, 'クラス機能はスクールプランまたは先生権限ユーザー限定です。')
        return redirect('users:upgrade')
    
    classroom = get_object_or_404(Classroom, pk=pk, is_active=True)
    
    # メンバーかホストのみアクセス可能
    is_member = ClassroomMembership.objects.filter(user=request.user, classroom=classroom).exists()
    is_host = classroom.host == request.user
    
    if not is_member and not is_host:
        if is_english:
            messages.error(request, 'You do not have access to this class.')
        elif is_chinese:
            messages.error(request, '您没有访问该班级的权限。')
        else:
            messages.error(request, 'このクラスにアクセスする権限がありません。')
        return redirect('songs:classroom_join')
    
    # クラス内の共有楽曲
    shared_songs = ClassroomSong.objects.filter(classroom=classroom).select_related('song', 'shared_by')
    
    # メンバー一覧
    members = ClassroomMembership.objects.filter(classroom=classroom).select_related('user')

    # 先生向け情報
    is_teacher_view = _is_teacher_user(request.user)
    student_members = []
    if is_teacher_view and is_host:
        member_qs = members.exclude(user=classroom.host).select_related('user')
        for membership in member_qs:
            student_user = membership.user
            completed_songs = Song.objects.filter(created_by=student_user, generation_status='completed')
            student_members.append({
                'membership': membership,
                'completed_song_count': completed_songs.count(),
                'public_song_count': completed_songs.filter(is_public=True).count(),
            })

    assignments = ClassroomAssignment.objects.filter(classroom=classroom).select_related('song', 'assigned_by')
    teacher_songs = Song.objects.none()
    if is_host and is_teacher_view:
        teacher_songs = Song.objects.filter(
            created_by=request.user,
            generation_status='completed',
        ).order_by('-created_at')
    
    return render(request, 'songs/classroom_detail.html', {
        'classroom': classroom,
        'shared_songs': shared_songs,
        'members': members,
        'student_members': student_members,
        'assignments': assignments,
        'teacher_songs': teacher_songs,
        'is_teacher_view': is_teacher_view,
        'is_host': is_host,
        'is_english': is_english,
        'is_chinese': is_chinese,
    })


@login_required
@require_POST
def classroom_assign_song(request, pk):
    """先生がクラスへ課題曲を出題"""
    app_language = request.session.get('app_language', 'ja')
    is_english = app_language == 'en'
    is_chinese = app_language == 'zh'

    classroom = get_object_or_404(Classroom, pk=pk, is_active=True)

    if classroom.host != request.user:
        if is_english:
            messages.error(request, 'Only the class host can assign tasks.')
        elif is_chinese:
            messages.error(request, '只有班级主持人可以发布课题。')
        else:
            messages.error(request, '課題を出題できるのはクラスホストのみです。')
        return redirect('songs:classroom_detail', pk=pk)

    if not _is_teacher_user(request.user):
        if is_english:
            messages.error(request, 'Teacher permission is required.')
        elif is_chinese:
            messages.error(request, '需要教师权限。')
        else:
            messages.error(request, '先生権限が必要です。')
        return redirect('songs:classroom_detail', pk=pk)

    song_id = request.POST.get('song_id', '').strip()
    due_date_raw = request.POST.get('due_date', '').strip()
    note = request.POST.get('note', '').strip()

    if not song_id:
        if is_english:
            messages.error(request, 'Please select a song to assign.')
        elif is_chinese:
            messages.error(request, '请选择要布置的歌曲。')
        else:
            messages.error(request, '課題にする曲を選んでください。')
        return redirect('songs:classroom_detail', pk=pk)

    try:
        song = Song.objects.get(pk=song_id, created_by=request.user, generation_status='completed')
    except Song.DoesNotExist:
        if is_english:
            messages.error(request, 'Selected song is not available.')
        elif is_chinese:
            messages.error(request, '所选歌曲不可用。')
        else:
            messages.error(request, '選択した曲は利用できません。')
        return redirect('songs:classroom_detail', pk=pk)

    due_date = None
    if due_date_raw:
        try:
            due_date = datetime.strptime(due_date_raw, '%Y-%m-%d').date()
        except ValueError:
            if is_english:
                messages.error(request, 'Due date format is invalid.')
            elif is_chinese:
                messages.error(request, '截止日期格式无效。')
            else:
                messages.error(request, '期限日の形式が不正です。')
            return redirect('songs:classroom_detail', pk=pk)

    assignment, created = ClassroomAssignment.objects.get_or_create(
        classroom=classroom,
        song=song,
        defaults={
            'assigned_by': request.user,
            'due_date': due_date,
            'note': note,
        },
    )

    if not created:
        assignment.assigned_by = request.user
        assignment.due_date = due_date
        assignment.note = note
        assignment.save(update_fields=['assigned_by', 'due_date', 'note'])

    # 課題化した曲はクラス共有一覧にも掲載
    ClassroomSong.objects.get_or_create(
        classroom=classroom,
        song=song,
        defaults={'shared_by': request.user},
    )

    if is_english:
        messages.success(request, 'Task has been assigned to the class.')
    elif is_chinese:
        messages.success(request, '课题已发布到班级。')
    else:
        messages.success(request, 'クラスに課題を出題しました。')

    return redirect('songs:classroom_detail', pk=pk)


@login_required
def classroom_share_song(request, pk):
    """楽曲をクラスに共有"""
    app_language = request.session.get('app_language', 'ja')
    is_english = app_language == 'en'
    is_chinese = app_language == 'zh'
    
    classroom = get_object_or_404(Classroom, pk=pk, is_active=True)
    
    # メンバーかホストのみ
    is_member = ClassroomMembership.objects.filter(user=request.user, classroom=classroom).exists()
    if not is_member:
        if is_english:
            messages.error(request, 'You are not a member of this class.')
        elif is_chinese:
            messages.error(request, '您不是该班级的成员。')
        else:
            messages.error(request, 'このクラスのメンバーではありません。')
        return redirect('songs:classroom_list')
    
    if request.method == 'POST':
        song_id = request.POST.get('song_id')
        try:
            song = Song.objects.get(pk=song_id, created_by=request.user)
            
            # 既に共有されているか確認
            if ClassroomSong.objects.filter(classroom=classroom, song=song).exists():
                if is_english:
                    messages.info(request, 'This song is already shared.')
                elif is_chinese:
                    messages.info(request, '这首歌曲已被分享。')
                else:
                    messages.info(request, 'この楽曲は既に共有されています。')
            else:
                ClassroomSong.objects.create(
                    classroom=classroom,
                    song=song,
                    shared_by=request.user
                )
                if is_english:
                    messages.success(request, 'Song shared to class!')
                elif is_chinese:
                    messages.success(request, '歌曲已分享到班级！')
                else:
                    messages.success(request, 'クラスに楽曲を共有しました！')
            
            return redirect('songs:classroom_detail', pk=pk)
            
        except Song.DoesNotExist:
            if is_english:
                messages.error(request, 'Song not found.')
            elif is_chinese:
                messages.error(request, '歌曲未找到。')
            else:
                messages.error(request, '楽曲が見つかりません。')
    
    # 自分の楽曲一覧
    my_songs = Song.objects.filter(
        created_by=request.user, 
        generation_status='completed'
    ).exclude(
        classroom_shares__classroom=classroom
    )
    
    return render(request, 'songs/classroom_share_song.html', {
        'classroom': classroom,
        'my_songs': my_songs,
        'is_english': is_english,
        'is_chinese': is_chinese,
    })


@login_required
def classroom_leave(request, pk):
    """クラスから退出"""
    app_language = request.session.get('app_language', 'ja')
    is_english = app_language == 'en'
    is_chinese = app_language == 'zh'
    
    classroom = get_object_or_404(Classroom, pk=pk)
    
    # ホストは退出できない
    if classroom.host == request.user:
        if is_english:
            messages.error(request, 'Host cannot leave the class. Please delete the class instead.')
        elif is_chinese:
            messages.error(request, '主持人不能退出班级。请删除班级。')
        else:
            messages.error(request, 'ホストはクラスから退出できません。クラスを削除してください。')
        return redirect('songs:classroom_detail', pk=pk)
    
    membership = ClassroomMembership.objects.filter(user=request.user, classroom=classroom).first()
    if membership:
        membership.delete()
        if is_english:
            messages.success(request, 'You have left the class.')
        elif is_chinese:
            messages.success(request, '您已退出班级。')
        else:
            messages.success(request, 'クラスから退出しました。')
    
    return redirect('songs:classroom_list')


@login_required
def classroom_delete(request, pk):
    """クラスを削除（ホストのみ）"""
    app_language = request.session.get('app_language', 'ja')
    is_english = app_language == 'en'
    is_chinese = app_language == 'zh'
    
    classroom = get_object_or_404(Classroom, pk=pk)
    
    if classroom.host != request.user:
        if is_english:
            messages.error(request, 'Only the host can delete the class.')
        elif is_chinese:
            messages.error(request, '只有主持人可以删除班级。')
        else:
            messages.error(request, 'ホストのみがクラスを削除できます。')
        return redirect('songs:classroom_detail', pk=pk)
    
    if request.method == 'POST':
        classroom.is_active = False
        classroom.save()
        if is_english:
            messages.success(request, 'Class has been deleted.')
        elif is_chinese:
            messages.success(request, '班级已删除。')
        else:
            messages.success(request, 'クラスを削除しました。')
        return redirect('songs:classroom_list')
    
    return redirect('songs:classroom_detail', pk=pk)

