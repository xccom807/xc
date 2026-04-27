from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (
    StringField,
    PasswordField,
    BooleanField,
    SubmitField,
    TextAreaField,
    SelectField,
    DecimalField,
)
from wtforms.fields.datetime import DateTimeLocalField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional
from wtforms.validators import NumberRange


class SignUpForm(FlaskForm):
    username = StringField("用户名", validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField("邮箱", validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField("密码", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        "确认密码",
        validators=[DataRequired(), EqualTo("password", message="两次输入的密码不一致")],
    )
    full_name = StringField("全名", validators=[Optional(), Length(max=120)])
    phone = StringField("电话", validators=[Optional(), Length(max=50)])
    location = StringField("所在地", validators=[Optional(), Length(max=120)])
    submit = SubmitField("注册")


class LoginForm(FlaskForm):
    email = StringField("邮箱", validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField("密码", validators=[DataRequired()])
    remember_me = BooleanField("记住我")
    submit = SubmitField("登录")


class RequestHelpForm(FlaskForm):
    title = StringField("标题", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("描述", validators=[DataRequired(), Length(min=10)])
    category = SelectField(
        "分类",
        choices=[
            ("烹饪", "烹饪"),
            ("清洁", "清洁"),
            ("搬运", "搬运"),
            ("辅导", "辅导"),
            ("跑腿", "跑腿"),
            ("技术支持", "技术支持"),
            ("其他", "其他"),
        ],
        validators=[DataRequired()],
    )
    location = StringField("地点", validators=[Optional(), Length(max=120)])
    datetime_needed = DateTimeLocalField(
        "所需日期和时间", format="%Y-%m-%dT%H:%M", validators=[Optional()]
    )
    duration_estimate = StringField("预计时长", validators=[Optional(), Length(max=120)])
    price_offered = DecimalField("出价", places=2, rounding=None, validators=[Optional()])
    is_volunteer = BooleanField("这是志愿服务/免费请求")
    skills_required = StringField("所需技能", validators=[Optional(), Length(max=200)])
    notes = TextAreaField("补充说明", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("发布求助")


class OfferHelpForm(FlaskForm):
    message = TextAreaField("给求助者的留言", validators=[DataRequired(), Length(min=5, max=2000)])
    availability = BooleanField("我有空并且可以开始")
    timeframe = StringField("预计完成时间", validators=[Optional(), Length(max=120)])
    submit = SubmitField("提交帮助")



class ProfileForm(FlaskForm):
    full_name = StringField("全名", validators=[Optional(), Length(max=120)])
    phone = StringField("电话", validators=[Optional(), Length(max=50)])
    location = StringField("所在地", validators=[Optional(), Length(max=120)])
    bio = TextAreaField("关于我", validators=[Optional(), Length(max=2000)])
    skills = StringField("技能", validators=[Optional(), Length(max=300)])
    avatar = FileField("上传头像", validators=[Optional(), FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'webp'], '仅支持图片文件')])
    latitude = DecimalField("纬度", places=6, rounding=None, validators=[Optional(), NumberRange(min=-90, max=90)])
    longitude = DecimalField("经度", places=6, rounding=None, validators=[Optional(), NumberRange(min=-180, max=180)])
    submit = SubmitField("保存更改")


class ForgotPasswordForm(FlaskForm):
    email = StringField("邮箱", validators=[DataRequired(), Email(), Length(max=120)])
    submit = SubmitField("发送重置链接")


class ResetPasswordForm(FlaskForm):
    password = PasswordField("新密码", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        "确认新密码",
        validators=[DataRequired(), EqualTo("password", message="两次输入的密码不一致")],
    )
    submit = SubmitField("重置密码")


class AcceptOfferForm(FlaskForm):
    submit = SubmitField("接受帮助")


class CompleteTaskForm(FlaskForm):
    submit = SubmitField("标记为已完成")


class ReviewForm(FlaskForm):
    rating = SelectField(
        "评分",
        choices=[("5", "★★★★★"), ("4", "★★★★"), ("3", "★★★"), ("2", "★★"), ("1", "★")],
        validators=[DataRequired()],
    )
    comment = TextAreaField("评论", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("提交评价")


class CancelRequestForm(FlaskForm):
    submit = SubmitField("取消求助")


class EditRequestForm(FlaskForm):
    title = StringField("标题", validators=[DataRequired(), Length(max=200)])
    description = TextAreaField("描述", validators=[DataRequired(), Length(min=10)])
    category = SelectField(
        "分类",
        choices=[
            ("烹饪", "烹饪"),
            ("清洁", "清洁"),
            ("搬运", "搬运"),
            ("辅导", "辅导"),
            ("跑腿", "跑腿"),
            ("技术支持", "技术支持"),
            ("其他", "其他"),
        ],
        validators=[DataRequired()],
    )
    location = StringField("地点", validators=[Optional(), Length(max=120)])
    datetime_needed = DateTimeLocalField(
        "所需日期和时间", format="%Y-%m-%dT%H:%M", validators=[Optional()]
    )
    duration_estimate = StringField("预计时长", validators=[Optional(), Length(max=120)])
    price_offered = DecimalField("出价", places=2, rounding=None, validators=[Optional()])
    is_volunteer = BooleanField("这是志愿服务/免费请求")
    skills_required = StringField("所需技能", validators=[Optional(), Length(max=200)])
    notes = TextAreaField("补充说明", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("保存修改")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("当前密码", validators=[DataRequired()])
    new_password = PasswordField("新密码", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        "确认新密码",
        validators=[DataRequired(), EqualTo("new_password", message="两次输入的密码不一致")],
    )
    submit = SubmitField("修改密码")


class FlagForm(FlaskForm):
    reason = SelectField(
        "举报原因",
        choices=[
            ("虚假信息", "虚假信息"),
            ("欺诈行为", "欺诈行为"),
            ("不当内容", "不当内容"),
            ("骚扰行为", "骚扰行为"),
            ("垃圾信息", "垃圾信息"),
            ("其他", "其他"),
        ],
        validators=[DataRequired()],
    )
    detail = TextAreaField("详细说明", validators=[Optional(), Length(max=500)])
    submit = SubmitField("提交举报")


class AppealForm(FlaskForm):
    reason = TextAreaField("申诉理由", validators=[DataRequired(), Length(min=10, max=1000)])
    submit = SubmitField("提交申诉")


class MessageForm(FlaskForm):
    content = TextAreaField("消息内容", validators=[DataRequired(), Length(min=1, max=2000)])
    submit = SubmitField("发送")
